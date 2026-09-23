"""Identifier generation.

Ids are prefixed by kind so that a journal line is readable without a
lookup. The generator is seedable because scenario output is compared
against golden files.
"""

from __future__ import annotations

import random
import string

_ALPHABET = string.ascii_lowercase + string.digits


class IdGenerator:
    def __init__(self, seed: int | None = None) -> None:
        self._rand = random.Random(seed)

    def new(self, kind: str, length: int = 8) -> str:
        body = "".join(self._rand.choice(_ALPHABET) for _ in range(length))
        return f"{kind}_{body}"

    def incident(self) -> str:
        return self.new("inc")

    def subtask(self) -> str:
        return self.new("sub")

    def escalation(self) -> str:
        return self.new("esc")

    def event(self) -> str:
        return self.new("evt", 12)


_default = IdGenerator()


def new_id(kind: str) -> str:
    return _default.new(kind)
