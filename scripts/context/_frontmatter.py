"""Deterministic YAML-subset parser for tech-context.md frontmatter (stdlib only).

Supported: block mappings and sequences (by indentation), flow sequences and
mappings (nested), single/double quoted scalars, plain scalars, booleans, null,
integers, `#` comments and `|`/`>` block scalars. Anchors, tags, aliases,
multi-document streams and complex keys are rejected, never guessed.
"""

from __future__ import annotations

import json
import re
from typing import Any


class FrontmatterError(ValueError):
    """The frontmatter is outside the supported subset or malformed."""


_KEY = re.compile(r"""^(?:"([^"]+)"|'([^']+)'|([A-Za-z0-9_][A-Za-z0-9_./-]*))\s*:(?:\s+|$)(.*)$""")


def _key(match: "re.Match[str]") -> tuple[str, str]:
    return next(g for g in match.groups()[:3] if g is not None), match.group(4).strip()
_INT = re.compile(r"^-?(?:0|[1-9][0-9]*)$")


def split_frontmatter(text: str) -> tuple[str, str] | None:
    """Return (frontmatter, body) for a `---` delimited document, else None."""
    match = re.match(r"\A---[ \t]*\n(.*?)\n---[ \t]*(?:\n|\Z)", text, re.DOTALL)
    if match is None:
        return None
    return match.group(1), text[match.end():]


def _strip_comment(line: str) -> str:
    quote = ""
    for index, char in enumerate(line):
        if quote:
            if char == quote:
                quote = ""
            continue
        if char in "\"'":
            quote = char
        elif char == "#" and (index == 0 or line[index - 1] in " \t"):
            return line[:index].rstrip()
    return line.rstrip()


def _scalar(token: str) -> Any:
    token = token.strip()
    if token == "":
        return None
    if token[0] in "&*!|>%@`":
        raise FrontmatterError(f"unsupported YAML syntax: {token[:20]!r}")
    if token.startswith('"'):
        try:
            value = json.loads(token)
        except json.JSONDecodeError as error:
            raise FrontmatterError(f"invalid double-quoted scalar: {error}") from None
        if not isinstance(value, str):
            raise FrontmatterError("invalid double-quoted scalar")
        return value
    if token.startswith("'"):
        if len(token) < 2 or not token.endswith("'"):
            raise FrontmatterError("unterminated single-quoted scalar")
        return token[1:-1].replace("''", "'")
    if token in ("true", "True"):
        return True
    if token in ("false", "False"):
        return False
    if token in ("null", "~", "Null"):
        return None
    if _INT.match(token):
        return int(token)
    return token


class _Flow:
    def __init__(self, text: str) -> None:
        self.text = text
        self.pos = 0

    def parse(self) -> Any:
        value = self.value()
        self.space()
        if self.pos != len(self.text):
            raise FrontmatterError(f"trailing flow content: {self.text[self.pos:][:20]!r}")
        return value

    def space(self) -> None:
        while self.pos < len(self.text) and self.text[self.pos] in " \t":
            self.pos += 1

    def value(self) -> Any:
        self.space()
        if self.pos >= len(self.text):
            raise FrontmatterError("unterminated flow collection")
        char = self.text[self.pos]
        if char == "[":
            return self.sequence()
        if char == "{":
            return self.mapping()
        return self.scalar()

    def scalar(self) -> Any:
        start = self.pos
        char = self.text[self.pos]
        if char in "\"'":
            self.pos += 1
            while self.pos < len(self.text):
                if self.text[self.pos] == "\\" and char == '"':
                    self.pos += 2
                    continue
                if self.text[self.pos] == char:
                    if char == "'" and self.text[self.pos + 1:self.pos + 2] == "'":
                        self.pos += 2
                        continue
                    self.pos += 1
                    return _scalar(self.text[start:self.pos])
                self.pos += 1
            raise FrontmatterError("unterminated quoted scalar")
        while self.pos < len(self.text) and self.text[self.pos] not in ",]}":
            if self.text[self.pos] == ":" and self.text[self.pos + 1:self.pos + 2] in (" ", ""):
                break
            self.pos += 1
        return _scalar(self.text[start:self.pos])

    def sequence(self) -> list[Any]:
        self.pos += 1
        items: list[Any] = []
        self.space()
        if self.text[self.pos:self.pos + 1] == "]":
            self.pos += 1
            return items
        while True:
            items.append(self.value())
            self.space()
            char = self.text[self.pos:self.pos + 1]
            self.pos += 1
            if char == "]":
                return items
            if char != ",":
                raise FrontmatterError("expected ',' or ']' in flow sequence")

    def mapping(self) -> dict[str, Any]:
        self.pos += 1
        result: dict[str, Any] = {}
        self.space()
        if self.text[self.pos:self.pos + 1] == "}":
            self.pos += 1
            return result
        while True:
            key = self.scalar()
            if not isinstance(key, str) or not key:
                raise FrontmatterError("flow mapping keys must be strings")
            self.space()
            if self.text[self.pos:self.pos + 1] != ":":
                raise FrontmatterError("expected ':' in flow mapping")
            self.pos += 1
            if key in result:
                raise FrontmatterError(f"duplicate key: {key}")
            result[key] = self.value()
            self.space()
            char = self.text[self.pos:self.pos + 1]
            self.pos += 1
            if char == "}":
                return result
            if char != ",":
                raise FrontmatterError("expected ',' or '}' in flow mapping")


def _inline(token: str) -> Any:
    token = token.strip()
    if token.startswith(("[", "{")):
        return _Flow(token).parse()
    return _scalar(token)


class _Block:
    def __init__(self, text: str) -> None:
        self.lines: list[tuple[int, str, str]] = []  # (indent, content, raw)
        for raw in text.splitlines():
            content = _strip_comment(raw)
            if not content.strip():
                self.lines.append((-1, "", raw))
                continue
            self.lines.append((len(content) - len(content.lstrip(" ")), content.strip(), raw))
        self.pos = 0

    def skip_blank(self) -> None:
        while self.pos < len(self.lines) and self.lines[self.pos][0] < 0:
            self.pos += 1

    def parse(self) -> Any:
        self.skip_blank()
        if self.pos >= len(self.lines):
            return {}
        value = self.node(self.lines[self.pos][0])
        self.skip_blank()
        if self.pos < len(self.lines):
            raise FrontmatterError(f"unexpected indentation: {self.lines[self.pos][1][:30]!r}")
        return value

    def node(self, indent: int) -> Any:
        self.skip_blank()
        content = self.lines[self.pos][1]
        if content == "-" or content.startswith("- "):
            return self.sequence(indent)
        return self.mapping(indent)

    def block_scalar(self, style: str, parent_indent: int) -> str:
        collected: list[str] = []
        block_indent = None
        while self.pos < len(self.lines):
            indent, _, raw = self.lines[self.pos]
            stripped_indent = len(raw) - len(raw.lstrip(" "))
            if raw.strip() and stripped_indent <= parent_indent:
                break
            if raw.strip() and block_indent is None:
                block_indent = stripped_indent
            collected.append(raw[block_indent:] if block_indent and raw.strip() else raw.strip())
            self.pos += 1
        while collected and not collected[-1]:
            collected.pop()
        joiner = "\n" if style.startswith("|") else " "
        return joiner.join(collected) + ("\n" if style == "|" else "")

    def value_after(self, rest: str, indent: int) -> Any:
        if rest in ("|", "|-", ">", ">-"):
            return self.block_scalar(rest, indent)
        if rest:
            return _inline(rest)
        self.skip_blank()
        if self.pos < len(self.lines):
            child_indent, child, _ = self.lines[self.pos]
            if child_indent > indent or (child_indent == indent and (child == "-" or child.startswith("- "))):
                return self.node(child_indent)
        return None

    def mapping(self, indent: int) -> dict[str, Any]:
        result: dict[str, Any] = {}
        while True:
            self.skip_blank()
            if self.pos >= len(self.lines):
                return result
            line_indent, content, _ = self.lines[self.pos]
            if line_indent < indent:
                return result
            if line_indent > indent:
                raise FrontmatterError(f"unexpected indentation: {content[:30]!r}")
            if content == "-" or content.startswith("- "):
                return result
            match = _KEY.match(content)
            if match is None:
                raise FrontmatterError(f"expected 'key: value': {content[:30]!r}")
            key, rest = _key(match)
            if key in result:
                raise FrontmatterError(f"duplicate key: {key}")
            self.pos += 1
            result[key] = self.value_after(rest, indent)

    def sequence(self, indent: int) -> list[Any]:
        items: list[Any] = []
        while True:
            self.skip_blank()
            if self.pos >= len(self.lines):
                return items
            line_indent, content, raw = self.lines[self.pos]
            if line_indent != indent or not (content == "-" or content.startswith("- ")):
                if line_indent > indent:
                    raise FrontmatterError(f"unexpected indentation: {content[:30]!r}")
                return items
            rest = content[1:].strip()
            if not rest:
                self.pos += 1
                items.append(self.value_after("", indent))
                continue
            if _KEY.match(rest) and not rest.startswith(("[", "{")):
                # "- key: value" opens a mapping whose keys align after "- ".
                item_indent = indent + (len(content) - len(rest))
                self.lines[self.pos] = (item_indent, rest, raw)
                items.append(self.mapping(item_indent))
                continue
            self.pos += 1
            items.append(_inline(rest))


def parse(text: str) -> Any:
    """Parse the supported subset; raise FrontmatterError on anything else."""
    return _Block(text).parse()
