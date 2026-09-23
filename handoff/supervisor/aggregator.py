"""Merging worker output, and noticing when workers disagree.

Fan out is easy. The hard part is what to do when the workers come back
and two of them say incompatible things.

The common answer is to average, or to take the highest confidence, or to
let the model reconcile it in a summarisation step. All three hide the
disagreement, and a hidden disagreement is exactly the state in which an
automated system should not be acting.

So contested hypotheses are surfaced, not resolved. A contested
hypothesis is a reason to ask a human even when the action it would
justify is low risk, because the uncertainty is about the diagnosis
rather than about the blast radius.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from handoff.agents.base import Finding, ProposedAction, WorkerResult


@dataclass(frozen=True)
class HypothesisView:
    name: str
    support: float = 0.0
    against: float = 0.0
    supporters: tuple[str, ...] = ()
    detractors: tuple[str, ...] = ()

    @property
    def net(self) -> float:
        return self.support - self.against

    @property
    def contested(self) -> bool:
        """Both sides have a real voice.

        Deliberately not "the net is small". A hypothesis with support
        0.9 and against 0.8 nets out near zero and so does one with 0.05
        and 0.04, but only the first represents two confident workers
        looking at the same incident and reaching opposite conclusions.
        """
        return bool(self.supporters) and bool(self.detractors)

    def describe(self) -> str:
        state = "contested" if self.contested else "clear"
        return (
            f"{self.name}: support {self.support:.2f} from {list(self.supporters)}, "
            f"against {self.against:.2f} from {list(self.detractors)} [{state}]"
        )


@dataclass
class Aggregate:
    findings: list[Finding] = field(default_factory=list)
    proposals: list[ProposedAction] = field(default_factory=list)
    hypotheses: dict[str, HypothesisView] = field(default_factory=dict)
    failures: list[WorkerResult] = field(default_factory=list)

    def confirmed(self, threshold: float = 0.6) -> list[str]:
        """Hypotheses supported strongly enough to act on, and uncontested."""
        return sorted(
            h.name for h in self.hypotheses.values() if not h.contested and h.support >= threshold
        )

    def actionable(self, threshold: float = 0.6) -> list[str]:
        """Hypotheses worth planning against: confirmed ones and contested ones.

        Contested belongs here even though it is explicitly not confirmed.
        A contested diagnosis is the case where a human most needs to see a
        concrete proposal, and withholding the proposal until the system is
        sure means the human is asked to adjudicate an abstraction. The
        supervisor raises the risk of anything addressing a contested
        hypothesis, so surfacing it costs a review rather than an action.
        """
        return sorted(set(self.confirmed(threshold)) | {v.name for v in self.contested()})

    def contested(self) -> list[HypothesisView]:
        return sorted(
            (h for h in self.hypotheses.values() if h.contested),
            key=lambda h: h.name,
        )

    def rejected(self, threshold: float = 0.6) -> list[str]:
        return sorted(
            h.name
            for h in self.hypotheses.values()
            if not h.contested and h.against >= threshold and h.support == 0.0
        )

    @property
    def degraded(self) -> bool:
        """True when some worker failed, so the picture is incomplete."""
        return bool(self.failures)

    def summary(self) -> str:
        lines = [h.describe() for h in sorted(self.hypotheses.values(), key=lambda h: h.name)]
        if self.failures:
            lines.append(
                f"degraded: {len(self.failures)} worker failure(s): "
                + ", ".join(f"{f.worker} ({f.error})" for f in self.failures)
            )
        return "\n".join(lines)


def aggregate(results: list[WorkerResult]) -> Aggregate:
    out = Aggregate()
    support: dict[str, float] = {}
    against: dict[str, float] = {}
    supporters: dict[str, list[str]] = {}
    detractors: dict[str, list[str]] = {}

    for result in results:
        if not result.ok:
            out.failures.append(result)
            continue
        out.findings.extend(result.findings)
        out.proposals.extend(result.proposals)
        for finding in result.findings:
            for name in finding.supports:
                support[name] = support.get(name, 0.0) + finding.confidence
                supporters.setdefault(name, []).append(finding.source)
            for name in finding.contradicts:
                against[name] = against.get(name, 0.0) + finding.confidence
                detractors.setdefault(name, []).append(finding.source)

    for name in sorted(set(support) | set(against)):
        out.hypotheses[name] = HypothesisView(
            name=name,
            support=round(support.get(name, 0.0), 4),
            against=round(against.get(name, 0.0), 4),
            supporters=tuple(sorted(set(supporters.get(name, ())))),
            detractors=tuple(sorted(set(detractors.get(name, ())))),
        )
    return out
