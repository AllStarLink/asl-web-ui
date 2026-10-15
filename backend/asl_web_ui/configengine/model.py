"""Asterisk's view of a configuration, reproducing ASL-patched Asterisk.

Follows main/config.c (config_text_file_load, process_text_line) plus the ASL
patch config_c_fix_template_inheritance_overrides (ASTERISK-30370), under
which ast_variable_retrieve() returns the LAST value of a key:

- #include / #tryinclude are expanded as text, relative to the configuration
  directory, with glob patterns; a missing #include rejects the whole file,
  a #tryinclude may match nothing. Includes nest at most 10 levels.
- An included file starts in the including file's current section; when it
  returns, the including file continues with its own current section.
- [name](a,b) copies a and b's variables at the moment the header is read;
  a and b must already be defined. (!) marks a template, (+) adds to an
  existing section.
- Section names match case-insensitively. Lookups skip templates, except
  when resolving inheritance (config.c's TEMPLATES=include filter), so a
  template's own values are invisible and [t](+) cannot extend a template.
- "key += value" appends the raw text after "=" (leading space kept) to the
  last value of key in the section, then trims the result.
- Every value remembers where it came from (file and line) and whether it
  was inherited from a template.

Errors that make Asterisk reject the whole file are recorded in
``Config.errors``; Asterisk stops at the first one, the model keeps going so
all of them can be reported.
"""

import glob as globlib
import os
from collections.abc import Callable
from dataclasses import dataclass, field

from .text import ConfigText

MAX_INCLUDE_LEVEL = 10


@dataclass
class Var:
    key: str
    value: str
    file: str
    line: int  # index into ConfigText.lines
    inherited_from: str | None = None  # template name, when copied from one
    operator: str = "="


@dataclass
class Category:
    name: str
    file: str
    line: int
    template: bool = False
    options: list[str] = field(default_factory=list)
    templates: list[str] = field(default_factory=list)
    vars: list[Var] = field(default_factory=list)
    extra_headers: list[tuple[str, int]] = field(default_factory=list)  # (+) additions

    def values(self, key: str) -> list[str]:
        return [v.value for v in self.vars if v.key.lower() == key.lower()]

    def value(self, key: str) -> str | None:
        """The value Asterisk uses: the last one (ASL patch, ASTERISK-30370)."""
        vals = self.values(key)
        return vals[-1] if vals else None

    def own(self) -> list[Var]:
        return [v for v in self.vars if v.inherited_from is None]

    def effective(self, key: str) -> Var | None:
        found = [v for v in self.vars if v.key.lower() == key.lower()]
        return found[-1] if found else None


@dataclass
class Problem:
    code: str
    file: str
    line: int | None
    detail: str = ""


@dataclass
class Config:
    root: str
    categories: list[Category] = field(default_factory=list)
    files: dict[str, ConfigText] = field(default_factory=dict)  # every file read, in order
    errors: list[Problem] = field(default_factory=list)  # Asterisk rejects the file
    notes: list[Problem] = field(default_factory=list)  # loaded, but something is ignored
    missing_root: bool = False

    @property
    def rejected(self) -> bool:
        return bool(self.errors)

    def get(self, name: str, include_templates: bool = False) -> Category | None:
        """First section with this name, as ast_category_get() finds it:
        case-insensitive, and skipping templates unless asked
        (config.c's does_category_match with TEMPLATES=include)."""
        for cat in self.categories:
            if cat.name.lower() == name.lower() and (include_templates or not cat.template):
                return cat
        return None

    def sections(self, name: str) -> list[Category]:
        return [c for c in self.categories if c.name.lower() == name.lower()]

    def value(self, section: str, key: str) -> str | None:
        cat = self.get(section)
        return cat.value(key) if cat else None


Reader = Callable[[str], bytes]


def _read(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()


class _Loader:
    def __init__(self, config_dir: str, reader: Reader, glob: Callable[[str], list[str]]):
        self.config_dir = config_dir
        self.reader = reader
        self.glob = glob
        self.current: Category | None = None  # cfg->current

    def resolve(self, name: str) -> list[str]:
        path = name if name.startswith("/") else os.path.join(self.config_dir, name)
        if any(ch in path for ch in "*?["):
            return sorted(self.glob(path))
        return [path]

    def load_file(self, cfg: Config, path: str, level: int, required: bool, origin: tuple[str, int] | None) -> bool:
        try:
            data = self.reader(path)
        except (FileNotFoundError, NotADirectoryError):
            return False
        except IsADirectoryError:
            cfg.notes.append(Problem("not_regular_file", path, None))
            return True
        text = ConfigText(data, path)
        cfg.files[path] = text
        cat = self.current  # an included file starts in the includer's section
        if text.unterminated_comment:
            cfg.notes.append(Problem("unterminated_comment", path, None))
        for index, line in enumerate(text.lines):
            if line.stray_block_end:
                cfg.notes.append(Problem("stray_block_end", path, index))
            if line.kind in ("blank", "comment"):
                continue
            if line.kind == "section":
                cat = self.section(cfg, path, index, line, cat)
            elif line.kind == "directive":
                self.directive(cfg, path, index, line, level)
            elif line.kind == "invalid":
                cfg.notes.append(Problem("no_equals", path, index, line.content))
            elif line.kind == "variable":
                if cat is None:
                    cfg.errors.append(Problem("no_category", path, index))
                    continue
                if not line.key:
                    cfg.notes.append(Problem("no_variable_name", path, index))
                    continue
                if line.escaped_name and line.content[1:2] < "!":
                    cfg.errors.append(Problem("invalid_escape", path, index))
                    continue
                self.variable(cat, path, index, line)
        return True

    def section(self, cfg: Config, path: str, index: int, line, current: Category | None) -> Category | None:
        if line.header_error:
            code = "no_closing_bracket" if "]" in line.header_error else "no_closing_paren"
            cfg.errors.append(Problem(code, path, index))
            return current
        options = [o for o in line.options]
        new = Category(line.name, path, index, options=options)
        target = new
        for opt in options:
            if opt == "!":
                new.template = True
            elif opt.startswith("+"):
                existing = cfg.get(line.name)
                if existing is None:
                    # Asterisk rejects the file here; keep the section so the
                    # rest of the file is still attributed for display and lint.
                    cfg.errors.append(Problem("addition_missing", path, index, line.name))
                    continue
                existing.extra_headers.append((path, index))
                existing.template = existing.template or new.template
                target = existing
            else:
                base = cfg.get(opt, include_templates=True)
                if base is None:
                    # Asterisk rejects the file here (see addition_missing).
                    cfg.errors.append(Problem("undefined_template", path, index, opt))
                    continue
                new.templates.append(opt)
                for v in base.vars:
                    new.vars.append(Var(v.key, v.value, v.file, v.line, v.inherited_from or opt, v.operator))
        if target is new:
            cfg.categories.append(new)
        self.current = target
        return target

    def directive(self, cfg: Config, path: str, index: int, line, level: int) -> None:
        if line.directive not in ("include", "tryinclude", "exec"):
            cfg.notes.append(Problem("unknown_directive", path, index, line.directive))
            return
        if line.argument is None:
            cfg.notes.append(Problem("directive_without_argument", path, index, line.directive))
            return
        if line.directive == "exec":
            cfg.notes.append(Problem("exec_not_modeled", path, index, line.argument))
            return
        if level >= MAX_INCLUDE_LEVEL:
            cfg.notes.append(Problem("include_too_deep", path, index))
            return
        required = line.directive == "include"
        matches = self.resolve(line.argument)
        found = False
        for match in matches:
            found = self.load_file(cfg, match, level + 1, required, (path, index)) or found
        if not found and required:
            cfg.errors.append(Problem("include_missing", path, index, line.argument))
        # The includer keeps its own current section (config.c's local "cat");
        # cfg->current stays wherever the included file left it.

    def variable(self, cat: Category, path: str, index: int, line) -> None:
        if line.operator == "+=":
            for v in reversed(cat.vars):
                if v.key == line.key:
                    v.value = (v.value + line.value_raw).strip()
                    return
        cat.vars.append(Var(line.key, line.value, path, index, None, line.operator))


def load(
    filename: str,
    config_dir: str = "/etc/asterisk",
    reader: Reader = _read,
    glob: Callable[[str], list[str]] = globlib.glob,
) -> Config:
    """Load ``filename`` (relative to ``config_dir``) the way Asterisk would."""
    loader = _Loader(config_dir, reader, glob)
    root = filename if filename.startswith("/") else os.path.join(config_dir, filename)
    cfg = Config(root)
    if not loader.load_file(cfg, root, 1, True, None):
        cfg.missing_root = True
    return cfg
