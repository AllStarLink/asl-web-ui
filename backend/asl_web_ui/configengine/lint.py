"""Findings about a configuration, with the consequence of each.

Severities (agreed rule, docs/design-notes.md section 8):

error    Asterisk rejects the whole file. Demonstrated in main/config.c and
         confirmed by tests/conformance against the installed ASL packages.
warning  The file loads, but something written in it is ignored or
         overridden.
info     Valid, but worth knowing.

Every finding says what happens and cites where Asterisk does it.
"""

import os
import re
from dataclasses import asdict, dataclass

from .model import Config, Problem

REJECTS = (
    "Asterisk rejects the entire file at this line, so every module that reads it gets nothing. "
    "For rpt.conf, app_rpt disables every node — on app_rpt 3.10.5 even a reload does, while still "
    "reporting success."
)

# Keys that legitimately appear more than once in a section.
REPEATABLE = {
    "register", "load", "noload", "preload", "require", "exten", "same", "include", "switch",
    "ignorepat", "allow", "disallow", "permit", "deny", "eventfilter", "setvar", "member",
}

# Keys repeatable only in one file, because that module walks every line with
# ast_variable_browse(). chan_iax2 binds each bindaddr in [general] (IPv4 and
# IPv6 side by side); chan_voter reads its bindaddr once, so it stays flagged.
REPEATABLE_IN = {
    "iax.conf": {"bindaddr"},
}

# An app_rpt scheduler entry value: minute hour dom month dow, each a number or *.
SCHEDULE_ENTRY = re.compile(r"\s*[\d*]+(\s+[\d*]+){4}\s*")


@dataclass
class Finding:
    severity: str  # error | warning | info
    code: str
    file: str  # path relative to the configuration directory
    line: int | None  # 1-based
    message: str
    why: str

    def as_dict(self) -> dict:
        return asdict(self)


def _rel(path: str, config_dir: str) -> str:
    try:
        rel = os.path.relpath(path, config_dir)
    except ValueError:
        return path
    return path if rel.startswith("..") else rel


def _lev(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _from_problem(cfg: Config, p: Problem, config_dir: str) -> Finding:
    file = _rel(p.file, config_dir)
    line = None if p.line is None else p.line + 1
    d = p.detail
    if p.code == "undefined_template":
        later = next((c for c in cfg.categories if c.name.lower() == d.lower()), None)
        if later is not None:
            where = f"line {later.line + 1}" + ("" if later.file == p.file else f" of {_rel(later.file, config_dir)}")
            msg = f"Uses template [{d}] before it is defined ({where}). Templates must come first."
        else:
            names = {c.name for c in cfg.categories}
            near = sorted((n for n in names if _lev(n.lower(), d.lower()) <= 2), key=lambda n: _lev(n, d))
            msg = f"Uses template [{d}], which is not defined in this file or the files it includes."
            if near:
                msg += f" Did you mean [{near[0]}]?"
        return Finding("error", p.code, file, line, msg, REJECTS + " (main/config.c: Inheritance requested, but category does not exist)")
    table = {
        "no_closing_bracket": ("error", "Section header is missing its closing ]."),
        "no_closing_paren": ("error", "Section header is missing the closing ) of its option list."),
        "addition_missing": ("error", f"[{d}](+) adds to a section that does not exist. Templates cannot be extended this way."),
        "no_category": ("error", "This setting comes before any [section] header."),
        "include_missing": ("error", f"#include target not found: {d}. Use #tryinclude if the file is optional."),
        "invalid_escape": ("error", "A backslash at the start of the line must be followed by a visible character."),
        "no_equals": ("warning", "This line has no =, so Asterisk ignores it."),
        "no_variable_name": ("warning", "This line has no setting name before the =, so Asterisk ignores it."),
        "unknown_directive": ("warning", f"Unknown directive #{d}. Asterisk ignores it (only #include, #tryinclude and #exec exist)."),
        "directive_without_argument": ("warning", f"#{d} needs a file name. Asterisk ignores it."),
        "stray_block_end": ("warning", "--; closes a block comment that was never opened. Asterisk ignores every line after this one."),
        "unterminated_comment": ("warning", "A ;-- block comment is never closed with --;, so the rest of the file is ignored."),
        "exec_not_modeled": ("info", f"#exec {d} runs a program; its output cannot be checked here."),
        "include_too_deep": ("warning", "Includes are nested more than 10 levels deep; Asterisk stops here."),
        "not_regular_file": ("warning", "An include matched something that is not a regular file; Asterisk ignores it."),
    }
    severity, msg = table.get(p.code, ("warning", p.code))
    why = REJECTS + " (main/config.c)" if severity == "error" else "The file loads, but this is ignored (main/config.c)."
    if p.code in ("stray_block_end", "unterminated_comment"):
        why = "The file loads, but everything after this point is treated as a comment (main/config.c)."
    if p.code == "exec_not_modeled":
        why = "#exec also needs execincludes = yes in asterisk.conf."
    return Finding(severity, p.code, file, line, msg, why)


def lint(cfg: Config, config_dir: str = "/etc/asterisk") -> list[Finding]:
    findings = [_from_problem(cfg, p, config_dir) for p in cfg.errors + cfg.notes]

    # rpt.conf scheduler stanzas: app_rpt walks every line with
    # ast_variable_browse() (apps/app_rpt.c), so one macro scheduled at
    # several times is several entries, not an override. A stanza can be
    # named by scheduler= elsewhere or swapped in later, so schedule-shaped
    # values are recognised on their own too.
    schedulers = {
        v.lower() for c in cfg.categories if not c.template and (v := c.value("scheduler"))
    }

    # The same key twice among a section's own lines: only the last counts.
    repeatable = REPEATABLE | REPEATABLE_IN.get(os.path.basename(cfg.root), set())
    for cat in cfg.categories:
        if cat.name.lower() in schedulers:
            continue
        seen: dict[str, object] = {}
        for var in cat.own():
            key = var.key.lower()
            if key in repeatable or var.operator == "+=":
                continue
            if key in seen:
                first = seen[key]
                if SCHEDULE_ENTRY.fullmatch(first.value) and SCHEDULE_ENTRY.fullmatch(var.value):
                    seen[key] = var
                    continue
                findings.append(Finding(
                    "warning", "duplicate_key", _rel(var.file, config_dir), var.line + 1,
                    f"{var.key} is set more than once in [{cat.name}]. This value (line {var.line + 1}) wins; "
                    f"the one on line {first.line + 1} is ignored.",
                    "ASL's Asterisk uses the last value of a key (ASL patch config_c_fix_template_inheritance_overrides, "
                    "ASTERISK-30370). Overriding a template value is normal and not flagged.",
                ))
            seen[key] = var

    # A section name used twice: lookups use the first one.
    first_by_name: dict[str, object] = {}
    for cat in cfg.categories:
        if cat.template:
            continue
        key = cat.name.lower()
        if key in first_by_name:
            first = first_by_name[key]
            findings.append(Finding(
                "warning", "duplicate_section", _rel(cat.file, config_dir), cat.line + 1,
                f"[{cat.name}] is defined more than once. Lookups by name use the first one "
                f"(line {first.line + 1}{'' if first.file == cat.file else ' of ' + _rel(first.file, config_dir)}).",
                "Asterisk keeps both sections; ast_category_get() returns the first match (main/config.c).",
            ))
        else:
            first_by_name[key] = cat

    order = {"error": 0, "warning": 1, "info": 2}
    findings.sort(key=lambda f: (order[f.severity], f.file, f.line or 0))
    return findings


def counts(findings: list[Finding]) -> dict[str, int]:
    out = {"error": 0, "warning": 0, "info": 0}
    for f in findings:
        out[f.severity] += 1
    return out
