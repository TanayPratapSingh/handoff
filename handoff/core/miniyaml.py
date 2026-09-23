"""A YAML subset reader, so the core stays dependency free.

This parses the subset the config files in config/ and evals/ actually
use: nested maps, lists of scalars, lists of maps, comments, block scalars
in both folded and literal form, and the scalar types null, bool, int,
float and string. It does not parse anchors, aliases, multi document
streams, flow style or tags, and it raises ConfigError rather than
guessing when it meets one.

Block scalars are resolved in the scanner rather than the parser, because
their content is literal text: a # inside a block is a hash, not the start
of a comment, and a blank line is a paragraph break rather than something
to skip.

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


_MISSING = object()


@dataclass(frozen=True)
class _Line:
    indent: int
    text: str
    number: int
    value: Any = _MISSING


def _fold(raw: list[str], style: str, chomp: str) -> str:
    """Resolve the body of a block scalar.

    style is "|" for literal, which keeps line breaks, or ">" for folded,
    which joins consecutive non empty lines with a space and treats a
    blank line as a paragraph break. chomp is "-" to strip the trailing
    newline, "+" to keep every trailing newline, or "" to clip to one.
    """
    if not raw:
        return ""
    strip = min((len(x) - len(x.lstrip(" ")) for x in raw if x.strip()), default=0)
    body = [x[strip:] if len(x) >= strip else "" for x in raw]
    while body and not body[-1].strip():
        body.pop()

    if style == "|":
        text = "\n".join(body)
    else:
        out: list[str] = []
        for line in body:
            if not line.strip():
                out.append("\n")
            elif out and out[-1] != "\n":
                out[-1] = out[-1] + " " + line.strip()
            else:
                out.append(line.strip())
        text = "".join(out) if any(x == "\n" for x in out) else " ".join(out)

    if chomp == "-":
        return text.rstrip("\n")
    if chomp == "+":
        return text + "\n"
    return text


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
    raw_lines = text.splitlines()
    skip_until = -1
    for number, raw in enumerate(raw_lines, start=1):
        if number <= skip_until:
            continue
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
                raise ConfigError(f"line {number}: {token!r} is outside the supported YAML subset")
        indent = len(raw) - len(raw.lstrip(" "))

        marker = _block_marker(stripped)
        if marker is not None:
            key, style, chomp = marker
            body: list[str] = []
            cursor = number
            while cursor < len(raw_lines):
                nxt = raw_lines[cursor]
                if nxt.strip() and (len(nxt) - len(nxt.lstrip(" "))) <= indent:
                    break
                body.append(nxt)
                cursor += 1
            skip_until = cursor
            lines.append(_Line(indent, f"{key}:", number, _fold(body, style, chomp)))
            continue

        lines.append(_Line(indent, content, number))
    return lines


def _block_marker(stripped: str) -> tuple[str, str, str] | None:
    """Recognise 'key: >', 'key: |', and their chomping variants."""
    if ":" not in stripped:
        return None
    key, _, rest = stripped.partition(":")
    rest = rest.strip()
    if rest not in (">", "|", ">-", "|-", ">+", "|+"):
        return None
    return key.strip(), rest[0], rest[1:]


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
        if line.value is not _MISSING:
            out[key] = line.value
            continue
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
        if ":" in item and item[0] not in "\"'":
            # "- key: value" starts a map whose remaining keys are indented
            # to the column of that first key. Continuation lines keep
            # their own indentation: rewriting them all to one level would
            # flatten any nested map inside the item, which is how
            # modified_args under a decision entry loses its contents.
            block_lines: list[_Line] = []
            while pos < len(lines) and lines[pos].indent > indent:
                block_lines.append(lines[pos])
                pos += 1
            child_indent = block_lines[0].indent if block_lines else indent + 2
            block = [_Line(child_indent, item, line.number, line.value), *block_lines]
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
