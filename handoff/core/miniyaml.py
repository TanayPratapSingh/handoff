"""A YAML subset reader, so the core stays dependency free.

This parses the subset the config files in config/ actually use: nested
maps, lists of scalars, lists of maps, comments, and the scalar types null,
bool, int, float and string. It does not parse anchors, aliases, multi
document streams, flow style, block scalars or tags, and it raises
ConfigError rather than guessing when it meets one.

The point is not to reimplement YAML. The point is that a reviewer can run
the test suite on a bare interpreter with no install step, and that the
config format still looks like the config format everyone expects.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from handoff.core.errors import ConfigError

_REJECTED = ("&", "*", "---", "<<:", "!!")


@dataclass(frozen=True)
class _Line:
    indent: int
    text: str
    number: int


def _strip_comment(text: str) -> str:
    """Remove a trailing comment, respecting quotes."""
    quote: str | None = None
    for i, ch in enumerate(text):
        if quote:
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "#" and (i == 0 or text[i - 1] in " \t"):
            return text[:i].rstrip()
    return text.rstrip()


def _scan(text: str) -> list[_Line]:
    lines: list[_Line] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        if "\t" in raw[: len(raw) - len(raw.lstrip())]:
            raise ConfigError(f"line {number}: tab used for indentation")
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        content = _strip_comment(stripped)
        if not content:
            continue
        for token in _REJECTED:
            if content.startswith(token):
                raise ConfigError(
                    f"line {number}: {token!r} is outside the supported YAML subset"
                )
        indent = len(raw) - len(raw.lstrip(" "))
        lines.append(_Line(indent, content, number))
    return lines


def _scalar(text: str) -> Any:
    if not text:
        return None
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return text[1:-1]
    lowered = text.lower()
    if lowered in ("null", "~"):
        return None
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if text.startswith("[") and text.endswith("]"):
        inner = text[1:-1].strip()
        if not inner:
            return []
        return [_scalar(part.strip()) for part in inner.split(",")]
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        pass
    return text


def _parse_block(lines: list[_Line], pos: int, indent: int) -> tuple[Any, int]:
    if lines[pos].text.startswith("- ") or lines[pos].text == "-":
        return _parse_list(lines, pos, indent)
    return _parse_map(lines, pos, indent)


def _parse_map(lines: list[_Line], pos: int, indent: int) -> tuple[dict[str, Any], int]:
    out: dict[str, Any] = {}
    while pos < len(lines) and lines[pos].indent == indent:
        line = lines[pos]
        if line.text.startswith("- "):
            break
        if ":" not in line.text:
            raise ConfigError(f"line {line.number}: expected 'key: value', got {line.text!r}")
        key, _, rest = line.text.partition(":")
        key = key.strip()
        rest = rest.strip()
        if key in out:
            raise ConfigError(f"line {line.number}: duplicate key {key!r}")
        pos += 1
        if rest:
            out[key] = _scalar(rest)
            continue
        if pos < len(lines) and lines[pos].indent > indent:
            out[key], pos = _parse_block(lines, pos, lines[pos].indent)
        else:
            out[key] = None
    return out, pos


def _parse_list(lines: list[_Line], pos: int, indent: int) -> tuple[list[Any], int]:
    out: list[Any] = []
    while pos < len(lines) and lines[pos].indent == indent and lines[pos].text.startswith("-"):
        line = lines[pos]
        item = line.text[1:].strip()
        pos += 1
        if not item:
            if pos < len(lines) and lines[pos].indent > indent:
                value, pos = _parse_block(lines, pos, lines[pos].indent)
                out.append(value)
            else:
                out.append(None)
            continue
        if ":" in item and not (item[0] in "\"'"):
            child_indent = indent + 2
            block = [_Line(child_indent, item, line.number)]
            while pos < len(lines) and lines[pos].indent > indent:
                block.append(_Line(child_indent, lines[pos].text, lines[pos].number))
                pos += 1
            value, _ = _parse_map(block, 0, child_indent)
            out.append(value)
        else:
            out.append(_scalar(item))
    return out, pos


def loads(text: str) -> Any:
    lines = _scan(text)
    if not lines:
        return {}
    base = lines[0].indent
    value, pos = _parse_block(lines, 0, base)
    if pos != len(lines):
        raise ConfigError(f"line {lines[pos].number}: unexpected indentation")
    return value


def load(path: str | Path) -> Any:
    p = Path(path)
    if not p.exists():
        raise ConfigError(f"config file not found: {p}")
    return loads(p.read_text(encoding="utf-8"))
