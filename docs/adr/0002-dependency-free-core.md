# ADR 0002: the core carries no third party dependencies

Status: accepted
Date: 2026-09-22

## Context

The natural dependency list for this project is pydantic for the
records, pyyaml for the config, and pytest for the suite.

## Decision

Everything under `handoff/` imports only the standard library. Config is
read by `handoff/core/miniyaml.py`, a YAML subset reader. Tests run under
`unittest`, which ships with Python. `pytest` and `ruff` are optional
dev extras and the suite passes with neither installed.

## Consequences

`python3 -m unittest discover -s tests` works on a clean checkout with no
install step and no virtualenv. For a project whose whole claim is about
what happens under operational pressure, being runnable in ten seconds by
somebody who has not read the README is worth more than the validation
ergonomics pydantic would provide.

The cost is `miniyaml.py`, which is roughly 190 lines that exist only
because pyyaml was declined. It parses a subset and raises `ConfigError`
naming the line when it meets anchors, aliases, flow style or multi
document streams, rather than guessing.

That file has already justified itself twice, and both times the bug
would have existed anyway in a different form:

Block scalars had to be resolved in the scanner rather than the parser,
because a `#` inside a folded block is a hash and not a comment. Getting
that wrong truncated the written rationale in every scenario file at the
first hash.

Nested maps inside list items were flattened by an early version, which
silently emptied `modified_args` in a scenario and produced an approval
with no edits. It surfaced only because `Decision.MODIFY` rejects missing
arguments.

If the config surface grows past what the subset covers, take pyyaml.
The line to watch is the first time somebody wants an anchor.
