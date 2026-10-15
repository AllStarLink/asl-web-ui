"""Lossless line model of an Asterisk configuration file.

A file is a list of lines, each keeping its exact original text (including
its line ending). Writing the file back joins the lines unchanged, so a file
that is read and written without edits is byte-identical. Bytes that are not
valid UTF-8 survive through the "surrogateescape" error handler.

Each line is also lexed the way Asterisk's main/config.c reads it
(config_text_file_load and process_text_line):

- ``;`` starts a comment unless escaped as ``\\;`` (the backslash is dropped)
- ``;--`` ... ``--;`` is a block comment, nestable and spanning lines
- a ``--;`` outside any block comment drives Asterisk's nesting counter
  negative, after which it ignores every following line; reproduced here so
  lint can warn about it
- leading and trailing whitespace is stripped; a UTF-8 BOM is ignored
- what remains is a section header (``[name](options)``), a directive
  (``#include``, ``#tryinclude``, ``#exec`` or unknown), or a variable
  (``name = value``, ``name => value``, ``name += value``)
"""

from dataclasses import dataclass, field

ENCODING = "utf-8"
ERRORS = "surrogateescape"
MAX_NESTED_COMMENTS = 128
BOM = "﻿"


@dataclass
class Line:
    raw: str  # exact text, including the line ending
    kind: str = "blank"  # blank | comment | section | directive | variable | invalid
    content: str = ""  # what Asterisk sees after removing comments, stripped
    # section
    name: str = ""
    options: list[str] = field(default_factory=list)
    header_error: str | None = None  # "no closing ']'" or "no closing ')'"
    # directive
    directive: str = ""
    argument: str | None = None
    # variable
    key: str = ""
    value: str = ""
    value_raw: str = ""  # value before whitespace stripping ("+=" keeps it)
    operator: str = "="  # "=", "=>" or "+="
    escaped_name: bool = False  # line started with a backslash
    # lexing details used by edits and lint
    comment_at: int | None = None  # index in text where a ";" comment starts
    simple: bool = True  # no escapes or block comments on this line
    stray_block_end: bool = False  # a "--;" outside any block comment

    @property
    def text(self) -> str:
        """The line without its line ending."""
        return self.raw.rstrip("\r\n")

    @property
    def ending(self) -> str:
        return self.raw[len(self.text):]


@dataclass
class _Stripped:
    content: str
    depth: int
    comment_at: int | None
    simple: bool
    stray: bool


def strip_comments(text: str, depth: int) -> _Stripped:
    """Port of config.c's per-line comment loop.

    ``depth`` is the block-comment nesting when the line starts. Returns the
    line's content as Asterisk processes it (not yet whitespace-stripped).
    """
    s = text
    pos = 0
    removed = 0  # backslashes removed so far (maps indexes back to ``text``)
    collecting = depth == 0
    start = 0
    out: list[str] = []
    simple = True
    stray = False
    while True:
        p = s.find(";", pos)
        if p < 0:
            break
        if p > pos and s[p - 1] == "\\":
            s = s[: p - 1] + s[p:]  # drop the backslash; ";" is now at p - 1
            removed += 1
            simple = False
            pos = p
            continue
        if s[p + 1:p + 3] == "--" and s[p + 3:p + 4] != "-":
            simple = False
            if depth < MAX_NESTED_COMMENTS:
                if depth == 0 and collecting:
                    out.append(s[start:p])
                    collecting = False
                depth += 1
            pos = p + 3
            continue
        if p >= pos + 2 and s[p - 2:p] == "--":
            simple = False
            if depth == 0:
                stray = True
            depth -= 1
            pos = p + 1
            if depth == 0:
                collecting = True
                start = pos
            continue
        if depth == 0:
            if collecting:
                out.append(s[start:p])
                collecting = False
            return _Stripped("".join(out), depth, p + removed, simple, stray)
        pos = p + 1
    if collecting and depth == 0 or collecting and stray:
        out.append(s[start:])
    return _Stripped("".join(out), depth, None, simple, stray)


def lex(line: Line, content: str) -> None:
    """Fill in the structured fields of ``line`` from its comment-free content."""
    text = content.strip()
    line.content = text
    if not text:
        line.kind = "comment" if line.text.strip() else "blank"
        return
    if text.startswith("["):
        line.kind = "section"
        close = text.find("]")
        if close < 0:
            line.header_error = "no closing ']'"
            line.name = text[1:].strip()
            return
        line.name = text[1:close]
        rest = text[close + 1:]
        if rest.startswith("("):
            end = rest.find(")")
            if end < 0:
                line.header_error = "no closing ')'"
                line.options = rest[1:].split(",")
                return
            line.options = rest[1:end].split(",")
        return
    if text.startswith("#"):
        line.kind = "directive"
        parts = text[1:].split(None, 1)
        line.directive = parts[0].lower() if parts else ""
        arg = parts[1].strip() if len(parts) > 1 else ""
        if arg[:1] in ('"', "<"):
            close = '"' if arg[0] == '"' else ">"
            if len(arg) > 1 and arg.endswith(close):
                arg = arg[1:-1]
        line.argument = arg or None
        return
    line.escaped_name = text.startswith("\\")
    body = text[1:] if line.escaped_name else text
    eq = body.find("=")
    if eq < 0:
        line.kind = "invalid"
        return
    line.kind = "variable"
    name, value = body[:eq], body[eq + 1:]
    if eq > 0 and name.endswith("+"):
        line.operator = "+="
        name = name[:-1]
    elif value.startswith(">"):
        line.operator = "=>"
        value = value[1:]
    line.key = name.strip()
    line.value_raw = value
    line.value = value.strip()


class ConfigText:
    """One file as a list of lines."""

    def __init__(self, data: bytes, path: str = ""):
        self.path = path
        text = data.decode(ENCODING, ERRORS)
        self.lines: list[Line] = [Line(raw) for raw in text.splitlines(keepends=True)]
        self.unterminated_comment = False
        self.relex()

    @classmethod
    def from_text(cls, text: str, path: str = "") -> "ConfigText":
        return cls(text.encode(ENCODING, ERRORS), path)

    def relex(self) -> None:
        depth = 0
        for index, line in enumerate(self.lines):
            text = line.text
            if index == 0 and text.startswith(BOM):
                text = text[len(BOM):]
            fresh = Line(line.raw)
            line.__dict__.update(fresh.__dict__)
            stripped = strip_comments(text, depth)
            depth = stripped.depth
            line.comment_at = stripped.comment_at
            line.simple = stripped.simple
            line.stray_block_end = stripped.stray
            lex(line, stripped.content)
        self.unterminated_comment = depth > 0

    def to_text(self) -> str:
        return "".join(line.raw for line in self.lines)

    def to_bytes(self) -> bytes:
        return self.to_text().encode(ENCODING, ERRORS)

    @property
    def newline(self) -> str:
        """The line ending most lines use; new lines copy it."""
        crlf = sum(1 for line in self.lines if line.raw.endswith("\r\n"))
        return "\r\n" if crlf * 2 > len(self.lines) else "\n"
