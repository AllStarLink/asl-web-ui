"""Asterisk's view of configuration files (includes, templates, values)."""

from asl_web_ui.configengine.model import load


def fs(files):
    """A fake filesystem: {relative path: text}."""
    root = "/etc/asterisk"
    data = {f"{root}/{k}": v.encode() for k, v in files.items()}

    def reader(path):
        if path not in data:
            raise FileNotFoundError(path)
        return data[path]

    def glob(pattern):
        import fnmatch
        return [p for p in data if fnmatch.fnmatch(p, pattern)]

    return dict(config_dir=root, reader=reader, glob=glob)


def test_last_value_wins_for_overrides_and_duplicates():
    cfg = load("rpt.conf", **fs({"rpt.conf": "[t](!)\nrxchannel = A\nduplex = 1\n[1999](t)\nrxchannel = B\nduplex = 2\nduplex = 3\n"}))
    node = cfg.get("1999")
    assert node.value("rxchannel") == "B" and node.value("duplex") == "3"
    assert node.values("duplex") == ["1", "2", "3"]
    assert cfg.get("t", include_templates=True).template and node.templates == ["t"]
    inherited = [v for v in node.vars if v.inherited_from]
    assert [(v.key, v.inherited_from) for v in inherited] == [("rxchannel", "t"), ("duplex", "t")]


def test_template_copied_at_header_time():
    cfg = load("x.conf", **fs({"x.conf": "[base]\na = 1\n[n](base)\n[base](+)\nb = 2\n"}))
    assert cfg.get("n").value("b") is None  # added to base after n inherited
    assert cfg.get("base").value("b") == "2"


def test_templates_are_hidden_and_cannot_be_extended():
    cfg = load("x.conf", **fs({"x.conf": "[t](!)\na = 1\n[n](t)\n[t](+)\nb = 2\n"}))
    assert cfg.get("t", include_templates=True).template
    assert [e.code for e in cfg.errors] == ["addition_missing"]


def test_section_names_are_case_insensitive():
    cfg = load("x.conf", **fs({"x.conf": "[General]\na = 1\n"}))
    assert cfg.value("general", "A") == "1"


def test_undefined_and_later_defined_templates_reject_the_file():
    cfg = load("x.conf", **fs({"x.conf": "[n](later)\na = 1\n[later](!)\n"}))
    assert cfg.rejected and [e.code for e in cfg.errors] == ["undefined_template"]
    assert cfg.get("n").value("a") == "1"  # still attributed for display


def test_header_errors():
    cfg = load("x.conf", **fs({"x.conf": "[a\n[b](c\n"}))
    assert [e.code for e in cfg.errors] == ["no_closing_bracket", "no_closing_paren"]


def test_variable_before_any_section_rejects():
    cfg = load("x.conf", **fs({"x.conf": "a = 1\n[s]\n"}))
    assert [e.code for e in cfg.errors] == ["no_category"]


def test_includes_and_current_section():
    cfg = load("rpt.conf", **fs({
        "rpt.conf": "[general]\n#include more.conf\nafter = yes\n#tryinclude custom/rpt/*.conf\n",
        "more.conf": "inherited_section_var = 1\n[fromfile]\nz = 9\n",
        "custom/rpt/a.conf": "[ca](!)\nx = 1\n",
    }))
    general = cfg.get("general")
    # An included file starts in the includer's section ...
    assert general.value("inherited_section_var") == "1"
    # ... and the includer continues in its own section afterwards.
    assert general.value("after") == "yes" and cfg.get("fromfile").value("after") is None
    assert cfg.get("ca", include_templates=True).template and not cfg.rejected
    assert list(cfg.files) == ["/etc/asterisk/rpt.conf", "/etc/asterisk/more.conf", "/etc/asterisk/custom/rpt/a.conf"]


def test_missing_include_rejects_but_tryinclude_does_not():
    assert [e.code for e in load("x.conf", **fs({"x.conf": "[s]\n#include nope.conf\n"})).errors] == ["include_missing"]
    assert not load("x.conf", **fs({"x.conf": "[s]\n#tryinclude nope/*.conf\n"})).rejected


def test_append_operator():
    cfg = load("x.conf", **fs({"x.conf": "[s]\nallow = ulaw\nallow += ,gsm\n"}))
    assert cfg.get("s").values("allow") == ["ulaw ,gsm"]  # raw text after "=" is appended
    cfg = load("x.conf", **fs({"x.conf": "[s]\nallow = ulaw\nallow += gsm\n"}))
    assert cfg.get("s").values("allow") == ["ulaw gsm"]  # Asterisk keeps the space


def test_notes_for_ignored_lines():
    cfg = load("x.conf", **fs({"x.conf": "[s]\nno equals\n#bogus\n#include\na = 1 --;\nb = 2\n"}))
    assert [n.code for n in cfg.notes] == ["no_equals", "unknown_directive", "directive_without_argument", "stray_block_end"]
    assert cfg.get("s").value("b") is None


def test_duplicate_sections_are_separate():
    cfg = load("x.conf", **fs({"x.conf": "[s]\na = 1\n[s]\na = 2\n"}))
    assert len(cfg.sections("s")) == 2 and cfg.get("s").value("a") == "1"
