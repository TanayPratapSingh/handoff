"""The supervisor.

It owns the loop: decompose, fan out, aggregate, decide, act. It is also
the only component in this system that calls a mutating tool, which is
what makes the escalation ladder load bearing rather than advisory.

Two decisions in here are worth arguing about.

The first is that a contested hypothesis raises the effective risk of any
action addressing it by one level. Disagreement about the diagnosis and
danger in the action are different kinds of uncertainty, but they have
the same remedy, which is a human. Treating them with one mechanism means
a low risk action justified by a contested diagnosis still gets looked
at, and nobody has to remember to wire up a separate check.

The second is that advance() never blocks. When the supervisor needs a
human it returns with state AWAITING_HUMAN and the caller drives the
clock. A supervisor that blocked on input would be untestable and would
also, in production, be a thread parked on a queue for six hours.
"""

from __future__ import annotations

from handoff.agents.base import ProposedAction, Subtask, WorkerContext, WorkerResult
from handoff.agents.registry import WorkerRegistry
from handoff.bus.events import Event, EventKind
from handoff.bus.journal import Journal
from handoff.core.clock import Clock
from handoff.core.errors import UnknownWorkerError
from handoff.core.ids import IdGenerator
from handoff.core.types import Risk
from handoff.escalation.engine import EscalationEngine
from handoff.escalation.request import EscalationState
from handoff.supervisor import planner
from handoff.supervisor.aggregator import aggregate
from handoff.supervisor.incident import ExecutedAction, Incident, IncidentRun, RunState
from handoff.tools.registry import ToolRegistry

_BUMP = {
    Risk.READ_ONLY: Risk.LOW,
    Risk.LOW: Risk.MEDIUM,
    Risk.MEDIUM: Risk.HIGH,
    Risk.HIGH: Risk.CRITICAL,
    Risk.CRITICAL: Risk.CRITICAL,
}


class Supervisor:
    def __init__(
        self,
        workers: WorkerRegistry,
        tools: ToolRegistry,
        engine: EscalationEngine,
        journal: Journal,
        clock: Clock,
        world,
        ids: IdGenerator | None = None,
        confidence_threshold: float = 0.6,
    ) -> None:
        self.workers = workers
        self.tools = tools
        self.engine = engine
        self.journal = journal
        self.clock = clock
        self.world = world
        self.ids = ids or IdGenerator()
        self.confidence_threshold = confidence_threshold

    # workers get a registry they cannot do damage with

    def _readonly_tools(self) -> ToolRegistry:
        filtered = ToolRegistry()
        for tool in self.tools.tools.values():
            if tool.risk is Risk.READ_ONLY:
                filtered.register(tool)
        return filtered

    def _emit(self, kind: EventKind, run: IncidentRun, **detail) -> Event:
        return self.journal.append(Event(
            kind=kind,
            incident_id=run.incident.id,
            at=self.clock.now(),
            detail=detail,
        ))

    # the loop

    def open(self, incident: Incident) -> IncidentRun:
        run = IncidentRun(incident=incident)
        self._emit(
            EventKind.INCIDENT_OPENED, run,
            title=incident.title, service=incident.service,
            severity=str(incident.severity), symptom=incident.symptom,
        )
        return run

    def advance(self, run: IncidentRun) -> IncidentRun:
        """Drive the run as far as it will go without a human.

        Returns when the run is terminal or blocked. Safe to call again
        after the caller has advanced the clock or recorded a decision.
        """
        guard = 0
        while not run.state.is_terminal:
            guard += 1
            if guard > 100:
                run.note("supervisor loop guard tripped")
                run.state = RunState.ABANDONED
                break

            if run.state is RunState.AWAITING_HUMAN:
                if not self._unblock(run):
                    return run
                continue
            if run.state is RunState.TRIAGE:
                run.state = RunState.PLANNING
                continue
            if run.state is RunState.PLANNING:
                self._do_plan(run)
                continue
            if run.state is RunState.DISPATCHING:
                self._do_dispatch(run)
                continue
            if run.state is RunState.AGGREGATING:
                self._do_aggregate(run)
                continue
            if run.state is RunState.DECIDING:
                self._do_decide(run)
                continue
            if run.state is RunState.ACTING:
                self._do_act(run)
                continue
            if run.state is RunState.VERIFYING:
                self._do_verify(run)
                continue
        return run

    # steps

    def _do_plan(self, run: IncidentRun) -> None:
        run.subtasks = planner.plan(run.incident, self.ids)
        self._emit(
            EventKind.PLAN_BUILT, run,
            subtasks=len(run.subtasks),
            capabilities=[s.capability for s in run.subtasks],
        )
        run.state = RunState.DISPATCHING

    def _do_dispatch(self, run: IncidentRun) -> None:
        ctx = WorkerContext(registry=self._readonly_tools(), world=self.world)
        done: set[str] = set()
        while True:
            batch = planner.ready(run.subtasks, done)
            if not batch:
                break
            for subtask in batch:
                run.results.append(self._run_subtask(run, subtask, ctx, done))
                done.add(subtask.id)
        run.state = RunState.AGGREGATING

    def _run_subtask(
        self, run: IncidentRun, subtask: Subtask, ctx: WorkerContext, done: set[str]
    ) -> WorkerResult:
        try:
            worker = self.workers.for_capability(subtask.capability)
        except UnknownWorkerError as exc:
            self._emit(
                EventKind.SUBTASK_FAILED, run,
                subtask=subtask.id, capability=subtask.capability, error=str(exc),
            )
            return WorkerResult.failed(subtask.id, f"<{subtask.capability}>", str(exc))

        self._emit(
            EventKind.SUBTASK_ROUTED, run,
            subtask=subtask.id, capability=subtask.capability, worker=worker.name,
        )
        if subtask.capability == "remediation":
            interim = aggregate([r for r in run.results if r.ok])
            subtask.args["hypotheses"] = interim.confirmed(self.confidence_threshold)

        self._emit(EventKind.SUBTASK_STARTED, run, subtask=subtask.id, worker=worker.name)
        try:
            result = worker.handle(subtask, ctx)
        except Exception as exc:  # a worker crash degrades the run, it does not end it
            self._emit(
                EventKind.SUBTASK_FAILED, run,
                subtask=subtask.id, worker=worker.name, error=repr(exc),
            )
            return WorkerResult.failed(subtask.id, worker.name, repr(exc))

        kind = EventKind.SUBTASK_FINISHED if result.ok else EventKind.SUBTASK_FAILED
        self._emit(
            kind, run, subtask=subtask.id, worker=worker.name,
            findings=len(result.findings), proposals=len(result.proposals),
            error=result.error,
        )
        return result

    def _do_aggregate(self, run: IncidentRun) -> None:
        run.aggregate = aggregate(run.results)
        self._emit(
            EventKind.FINDINGS_MERGED, run,
            findings=len(run.aggregate.findings),
            confirmed=run.aggregate.confirmed(self.confidence_threshold),
            failures=len(run.aggregate.failures),
        )
        for view in run.aggregate.contested():
            self._emit(
                EventKind.CONFLICT_DETECTED, run,
                hypothesis=view.name,
                supporters=list(view.supporters), detractors=list(view.detractors),
            )
            run.note(f"contested diagnosis: {view.describe()}")
        run.state = RunState.DECIDING

    def _do_decide(self, run: IncidentRun) -> None:
        confirmed = set(run.aggregate.confirmed(self.confidence_threshold))
        contested = {v.name for v in run.aggregate.contested()}
        queue: list[ProposedAction] = []
        for proposal in run.aggregate.proposals:
            if proposal.addresses and proposal.addresses not in confirmed | contested:
                run.note(
                    f"dropped {proposal.tool}: it addresses {proposal.addresses!r}, "
                    f"which the evidence does not support"
                )
                continue
            queue.append(proposal)
        run.queue = queue
        if not queue:
            run.note("no supported remediation, nothing to do")
            run.state = RunState.RESOLVED if not run.aggregate.degraded else RunState.ABANDONED
            self._emit(EventKind.INCIDENT_CLOSED, run, why="no supported remediation")
            return
        run.state = RunState.ACTING

    def effective_risk(self, proposal: ProposedAction, run: IncidentRun) -> Risk:
        """Declared tool risk, raised one level if the diagnosis is contested."""
        base = self.tools.get(proposal.tool).risk
        contested = {v.name for v in run.aggregate.contested()}
        if proposal.addresses and proposal.addresses in contested:
            return _BUMP[base]
        return base

    def _do_act(self, run: IncidentRun) -> None:
        if not run.queue:
            run.state = RunState.VERIFYING
            return
        proposal = run.queue[0]
        tool = self.tools.get(proposal.tool)
        risk = self.effective_risk(proposal, run)

        self._emit(
            EventKind.ACTION_PROPOSED, run,
            tool=proposal.tool, args=proposal.args, reason=proposal.reason,
            declared_risk=str(tool.risk), effective_risk=str(risk),
        )

        if self.engine.policy.forbids(risk):
            run.queue.pop(0)
            run.note(f"policy at autonomy {self.engine.policy.autonomy} forbids {tool.name}")
            self._emit(EventKind.POLICY_BLOCKED, run, tool=tool.name, risk=str(risk))
            return

        if self.engine.policy.needs_human(risk):
            reason = proposal.reason
            if risk is not tool.risk:
                reason += f" (risk raised to {risk}: the diagnosis is contested)"
            escalation = self.engine.raise_for(run.incident.id, tool, proposal.args, reason)
            run.escalation_ids.append(escalation.id)
            if escalation.state.is_terminal:
                self._settle(run, escalation.id)
                return
            run.blocked_on = escalation.id
            run.state = RunState.AWAITING_HUMAN
            return

        run.queue.pop(0)
        self._execute(run, tool.name, proposal.args)

    def _unblock(self, run: IncidentRun) -> bool:
        """True when the escalation is settled and the run may continue."""
        assert run.blocked_on is not None
        escalation = self.engine.get(run.blocked_on)
        if escalation.state is EscalationState.HELD:
            run.state = RunState.FROZEN
            run.note(f"frozen: {escalation.resolution_note}")
            return True
        if escalation.state.is_open:
            return False
        self._settle(run, run.blocked_on)
        return True

    def _settle(self, run: IncidentRun, escalation_id: str) -> None:
        escalation = self.engine.get(escalation_id)
        resolution = self.engine.resolution(escalation)
        run.blocked_on = None
        if run.queue:
            run.queue.pop(0)
        if not resolution.should_run:
            run.note(f"{escalation.tool} not taken: {resolution.note}")
            run.state = RunState.ACTING if run.queue else RunState.VERIFYING
            return
        self._execute(
            run,
            resolution.tool,
            resolution.args,
            approved_by=", ".join(escalation.approvals) or "timeout fallback",
            substituted_for=escalation.tool if resolution.substituted else "",
        )

    def _execute(
        self,
        run: IncidentRun,
        tool_name: str,
        args: dict,
        approved_by: str = "",
        substituted_for: str = "",
    ) -> None:
        tool = self.tools.get(tool_name)
        try:
            validated = tool.validate(args)
            result = tool.run(self.world, validated)
        except Exception as exc:
            run.executed.append(ExecutedAction(
                tool=tool_name, args=args, result=None, at=self.clock.now(),
                ok=False, error=repr(exc),
                approved_by=approved_by, substituted_for=substituted_for,
            ))
            self._emit(EventKind.ACTION_FAILED, run, tool=tool_name, error=repr(exc))
            run.state = RunState.ACTING if run.queue else RunState.VERIFYING
            return
        run.executed.append(ExecutedAction(
            tool=tool_name, args=validated, result=result, at=self.clock.now(),
            approved_by=approved_by, substituted_for=substituted_for,
        ))
        self._emit(
            EventKind.ACTION_EXECUTED, run,
            tool=tool_name, args=validated, approved_by=approved_by,
            substituted_for=substituted_for,
        )
        run.state = RunState.VERIFYING

    def _do_verify(self, run: IncidentRun) -> None:
        try:
            metrics = self.tools.get("read_metrics")
            out = metrics.run(self.world, metrics.validate({"service": run.incident.service}))
        except Exception as exc:
            run.note(f"verification could not read metrics: {exc!r}")
            run.state = RunState.ABANDONED
            return
        healthy = not out["saturated"]
        if healthy:
            run.note(f"verified: p99 is {out['latency_p99_ms']}ms and no longer saturated")
            run.state = RunState.RESOLVED
            self._emit(EventKind.INCIDENT_CLOSED, run, why="verified healthy", metrics=out)
            return
        if run.queue:
            run.note(f"still saturated at {out['latency_p99_ms']}ms, trying the next action")
            run.state = RunState.ACTING
            return
        run.note(f"still saturated at {out['latency_p99_ms']}ms and out of options")
        run.state = RunState.ABANDONED
        self._emit(EventKind.INCIDENT_CLOSED, run, why="options exhausted", metrics=out)
