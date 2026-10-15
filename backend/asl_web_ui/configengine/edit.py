"""Small, lossless edits to configuration files.

Guided pages never rewrite a file. They express intents (set a key, remove
a section, rename a section ...) that change only the lines involved; every
other line keeps its exact bytes. The edits are made on a Workspace: working
copies of the files that the Asterisk model (model.load) can read, so each
step sees the effect of the previous ones and the final result can be
diffed, linted and applied as one plan.

Where Asterisk takes a value from matters: a key set in an included file is
changed in that file, a value that only comes from a template gets an
override line in the section itself, and templates are never edited.
"""

import os
import re
from collections.abc import Callable

from .model import Category, Config, load
from .store import FileChange, Store, digest
from .text import ConfigText, Line


class EditError(Exception):
    """An intent cannot be carried out on the file as it is."""


class Workspace:
    """Working copies of the files under a configuration directory."""

    def __init__(self, config_dir: str, reader: Callable[[str], bytes | None] = Store.read):
        self.config_dir = config_dir
        self._reader = reader
        self.texts: dict[str, ConfigText] = {}
        self.originals: dict[str, bytes | None] = {}

    def path(self, name: str) -> str:
        return name if name.startswith("/") else os.path.join(self.config_dir, name)

    def _load(self, path: str) -> ConfigText | None:
        if path not in self.originals:
            data = self._reader(path)
            self.originals[path] = data
            if data is not None:
                self.texts[path] = ConfigText(data, path)
        return self.texts.get(path)

    def exists(self, name: str) -> bool:
        return self._load(self.path(name)) is not None

    def text(self, name: str, create: bool = False) -> ConfigText:
        path = self.path(name)
        text = self._load(path)
        if text is None:
            if not create:
                raise EditError(f"{os.path.relpath(path, self.config_dir)} does not exist")
            text = ConfigText(b"", path)
            self.texts[path] = text
        return text

    def read_bytes(self, path: str) -> bytes:
        text = self._load(path)
        if text is None:
            raise FileNotFoundError(path)
        return text.to_bytes()

    def model(self, name: str) -> Config:
        return load(name, config_dir=self.config_dir, reader=self.read_bytes)

    def changes(self) -> list[FileChange]:
        out = []
        for path, text in self.texts.items():
            new = text.to_bytes()
            old = self.originals.get(path)
            if new != old:
                out.append(FileChange(path, digest(old), new, old))
        return out


# ---- line helpers ----------------------------------------------------------

_VAR = re.compile(r"^(?P<lead>\s*)(?P<key>[^=]*?)(?P<before>\s*)(?P<op>\+=|=>|=)(?P<after>\s*)")


def _escape(value: str) -> str:
    if "\n" in value or "\r" in value:
        raise EditError("Values cannot contain line breaks")
    return value.replace(";", "\\;")


def _style(text: ConfigText, near: int | None) -> tuple[str, str]:
    """Spacing around "=" used by the variable line nearest to ``near``."""
    if near is not None:
        order = sorted(range(len(text.lines)), key=lambda i: abs(i - near))
        for i in order:
            line = text.lines[i]
            if line.kind == "variable" and line.simple and line.operator == "=":
                m = _VAR.match(line.text)
                if m:
                    return m.group("before"), m.group("after")
    return " ", " "


def var_line(text: ConfigText, key: str, value: str, near: int | None = None, operator: str = "=") -> str:
    before, after = _style(text, near)
    value = _escape(value)
    if not value:
        after = ""
    return f"{key}{before}{operator}{after}{value}".rstrip() + text.newline


def replace_value(line: Line, value: str, newline: str) -> str:
    """The line with its value replaced, keeping spacing and any comment."""
    value = _escape(value)
    text = line.text
    m = _VAR.match(text)
    if line.simple and m:
        start = m.end()
        end = line.comment_at if line.comment_at is not None else len(text)
        tail = text[end:]
        old = text[start:end]
        gap = old[len(old.rstrip()):] if tail else ""
        if not value and not tail:
            new = text[:start].rstrip()
        else:
            new = text[:start] + value + (gap or (" " if tail and value else "")) + tail
        return new + (line.ending or newline)
    # Escapes or block comments on the line: write it plainly, keeping a
    # trailing ";" comment if there is one.
    new = f"{line.key} {line.operator} {value}".rstrip()
    if line.comment_at is not None:
        new += " " + text[line.comment_at:]
    return new + (line.ending or newline)


def header_line(name: str, options: list[str], old: Line | None, newline: str) -> str:
    head = f"[{name}]" + (f"({','.join(options)})" if options else "")
    if old is None:
        return head + newline
    text = old.text
    tail = ""
    if old.comment_at is not None:
        tail = text[old.comment_at:]
        gap = text[:old.comment_at]
        tail = gap[len(gap.rstrip()):] + tail
    lead = text[:len(text) - len(text.lstrip())]
    return lead + head + tail + (old.ending or newline)


def ensure_final_newline(text: ConfigText) -> None:
    if text.lines and not text.lines[-1].ending:
        text.lines[-1] = Line(text.lines[-1].raw + text.newline)


def insert(text: ConfigText, index: int, raws: list[str]) -> None:
    if index >= len(text.lines):
        ensure_final_newline(text)
    text.lines[index:index] = [Line(r) for r in raws]
    text.relex()


def delete(text: ConfigText, indexes: list[int]) -> None:
    for i in sorted(set(indexes), reverse=True):
        del text.lines[i]
    text.relex()


def set_raw(text: ConfigText, index: int, raw: str) -> None:
    text.lines[index] = Line(raw)
    text.relex()


# ---- sections within one file -------------------------------------------------


def find_headers(text: ConfigText, name: str) -> list[int]:
    return [i for i, line in enumerate(text.lines)
            if line.kind == "section" and not line.header_error and line.name.lower() == name.lower()]


def section_end(text: ConfigText, header: int) -> int:
    """Index of the next section header after ``header`` (or the file's end)."""
    for i in range(header + 1, len(text.lines)):
        if text.lines[i].kind == "section":
            return i
    return len(text.lines)


def section_vars(text: ConfigText, header: int, key: str) -> list[int]:
    return [i for i in range(header + 1, section_end(text, header))
            if text.lines[i].kind == "variable" and text.lines[i].key.lower() == key.lower()]


def last_var(text: ConfigText, header: int) -> int:
    """Index after which a new variable line of this section goes."""
    last = header
    for i in range(header + 1, section_end(text, header)):
        if text.lines[i].kind in ("variable", "directive"):
            last = i
    return last


def append_section(text: ConfigText, name: str, options: list[str], body: list[str] | None = None,
                   before: int | None = None) -> int:
    """Add ``[name](options)`` with ``body`` lines; returns the header index.

    Goes at the end of the file (after a blank line), or just before the
    line ``before`` (followed by a blank line) when given.
    """
    nl = text.newline
    body = [b if b.endswith("\n") else b + nl for b in (body or [])]
    head = header_line(name, options, None, nl)
    if before is None:
        ensure_final_newline(text)
        lead = [] if not text.lines or not text.lines[-1].text.strip() else [nl]
        index = len(text.lines) + len(lead)
        insert(text, len(text.lines), lead + [head] + body)
        return index
    insert(text, before, [head] + body + [nl])
    return before


# ---- section-level intents across includes -----------------------------------


def _own_lines(cfg: Config, cat: Category, key: str) -> list[tuple[str, int]]:
    """(file, line) of every line in the section itself that sets ``key``."""
    return [(v.file, v.line) for v in cat.vars if v.inherited_from is None and v.key.lower() == key.lower()]


class Section:
    """A section as Asterisk sees it, for editing.

    ``file`` and ``header`` locate the header line; values may also come
    from included files (the section continues into them) and templates.
    """

    def __init__(self, ws: Workspace, filename: str, name: str):
        self.ws = ws
        self.filename = filename
        self.name = name

    def category(self) -> Category | None:
        return self.ws.model(self.filename).get(self.name)

    def require(self) -> Category:
        cat = self.category()
        if cat is None:
            raise EditError(f"[{self.name}] is not defined in {self.filename}")
        return cat

    def value(self, key: str) -> str | None:
        cat = self.category()
        return cat.value(key) if cat else None

    def set(self, key: str, value: str) -> None:
        """Set ``key``: change the line Asterisk uses (D1), or add an override
        line to the section when the value only comes from a template or is
        not set at all."""
        cat = self.require()
        own = _own_lines(self.ws.model(self.filename), cat, key)
        if own:
            path, index = own[-1]
            text = self.ws.text(path)
            line = text.lines[index]
            if line.value != value:
                set_raw(text, index, replace_value(line, value, text.newline))
            if self.value(key) != value:
                # A later "key += ..." appends to it; a plain line after the
                # last mention replaces the result.
                last = max(i for i in range(index, section_end(text, index))
                           if text.lines[i].kind == "variable" and text.lines[i].key.lower() == key.lower())
                set_raw(text, index, line.raw)
                insert(text, last + 1, [var_line(text, key, value, near=last)])
            return
        text = self.ws.text(cat.file)
        after = last_var(text, cat.line)
        insert(text, after + 1, [var_line(text, key, value, near=after)])

    def redundant(self, key: str) -> list[tuple[str, int]]:
        """Earlier lines for ``key`` in the section that the last one overrides."""
        cat = self.category()
        if cat is None:
            return []
        return _own_lines(self.ws.model(self.filename), cat, key)[:-1]

    def unset(self, key: str) -> None:
        """Remove the section's own lines for ``key`` (template values stay)."""
        cat = self.category()
        if cat is None:
            return
        by_file: dict[str, list[int]] = {}
        for path, index in _own_lines(self.ws.model(self.filename), cat, key):
            by_file.setdefault(path, []).append(index)
        for path, indexes in by_file.items():
            delete(self.ws.text(path), indexes)

    def set_templates(self, templates: list[str]) -> None:
        cat = self.require()
        text = self.ws.text(cat.file)
        line = text.lines[cat.line]
        options = [o for o in line.options if o == "!" or o.startswith("+")] + templates
        set_raw(text, cat.line, header_line(line.name, options, line, text.newline))

    def rename(self, new: str) -> None:
        cat = self.require()
        for path, index in [(cat.file, cat.line)] + cat.extra_headers:
            text = self.ws.text(path)
            line = text.lines[index]
            set_raw(text, index, header_line(new, line.options, line, text.newline))
        self.name = new


def remove_section(text: ConfigText, header: int, keep_comment: Callable[[str], bool] | None = None) -> None:
    """Delete a section from its header to the next header.

    Comment and blank lines at the end of the span usually introduce the
    *next* section, so they stay unless ``keep_comment`` rejects them (D5:
    comments that mention the removed node go too). One blank line is left
    between the neighbours.
    """
    end = section_end(text, header)
    tail = end
    while tail > header + 1 and text.lines[tail - 1].kind in ("comment", "blank"):
        tail -= 1
    trailing = list(range(tail, end))
    drop = list(range(header, tail))
    if keep_comment is not None:
        drop += [i for i in trailing if text.lines[i].kind == "comment" and not keep_comment(text.lines[i].text)]
    # Comments directly above the header that mention it go too (D5).
    above = header - 1
    while above >= 0 and text.lines[above].kind == "comment":
        if keep_comment is not None and not keep_comment(text.lines[above].text):
            drop.append(above)
            above -= 1
        else:
            break
    delete(text, drop)
    # Collapse the blank lines left where the section was.
    start = min(drop)
    i = start
    while 0 < i < len(text.lines) and text.lines[i].kind == "blank" and text.lines[i - 1].kind == "blank":
        delete(text, [i])


def comment_out(text: ConfigText, index: int) -> None:
    set_raw(text, index, ";" + text.lines[index].raw)


# ---- modules.conf -------------------------------------------------------------


def set_module(ws: Workspace, module: str, load_it: bool) -> None:
    """``load = module`` or ``noload = module`` in modules.conf [modules].

    Changes the line that names the module (keeping its spacing and comment);
    adds one when the module is to be loaded and no line names it (with
    autoload = no, Asterisk loads only what is listed).
    """
    text = ws.text("modules.conf")
    headers = find_headers(text, "modules")
    if not headers:
        raise EditError("modules.conf has no [modules] section")
    header = headers[0]
    wanted = "load" if load_it else "noload"
    base = module.removesuffix(".so")
    found = False
    for i in range(header + 1, section_end(text, header)):
        line = text.lines[i]
        if line.kind != "variable" or line.key.lower() not in ("load", "noload", "preload", "require", "preload-require"):
            continue
        if line.value.removesuffix(".so") != base:
            continue
        found = True
        if line.key.lower() in ("preload", "require", "preload-require") or line.key.lower() == wanted:
            continue
        m = _VAR.match(line.text)
        if line.simple and m:
            # Keep the "=" in the same column when the keyword's length changes.
            before = m.group("before")
            if before:
                before = " " * max(len(before) + len(line.key) - len(wanted), 1)
            raw = m.group("lead") + wanted + before + line.text[m.start("op"):] + (line.ending or text.newline)
        else:
            raw = f"{wanted} = {line.value}{text.newline}"
        set_raw(text, i, raw)
    if not found and load_it:
        after = last_var(text, header)
        insert(text, after + 1, [var_line(text, "load", f"{base}.so", near=after)])


def module_state(ws: Workspace, module: str) -> bool | None:
    """True if modules.conf loads the module, False if noload, None if unlisted."""
    cfg = ws.model("modules.conf")
    cat = cfg.get("modules")
    if cat is None:
        return None
    base = module.removesuffix(".so")
    keys = {v.key.lower() for v in cat.vars if v.value.removesuffix(".so") == base}
    # loader.c drops "noload" modules from the load list, whatever the order.
    if "noload" in keys:
        return False
    if keys & {"load", "preload", "require", "preload-require"}:
        return True
    if (cat.value("autoload") or "no").lower() in ("yes", "true", "1", "on"):
        return True
    return None
