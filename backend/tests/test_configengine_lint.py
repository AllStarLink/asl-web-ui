"""Lint findings and their severities."""

from asl_web_ui.configengine.lint import counts, lint
from asl_web_ui.configengine.model import load
from test_configengine_model import fs


def findings(text, **extra):
    files = {"rpt.conf": text, **extra}
    return lint(load("rpt.conf", **fs(files)))


def test_clean_file_has_no_findings():
    assert findings("[node-main](!)\nduplex = 1\n[1999](node-main)\nduplex = 2\n") == []


def test_misspelled_template_suggests_the_right_one():
    (f,) = findings("[node-main](!)\na = 1\n[1999](node-mian)\n")
    assert f.severity == "error" and f.code == "undefined_template" and f.line == 3
    assert "Did you mean [node-main]?" in f.message and "rejects the entire file" in f.why


def test_template_defined_later():
    (f,) = findings("[1999](later)\n[later](!)\n")
    assert "before it is defined (line 2)" in f.message


def test_duplicate_key_is_a_warning_naming_the_winner():
    (f,) = findings("[s]\nduplex = 1\nduplex = 2\n")
    assert (f.severity, f.code, f.line) == ("warning", "duplicate_key", 3)
    assert "line 2 is ignored" in f.message


def test_overriding_a_template_value_is_not_flagged():
    assert findings("[t](!)\nduplex = 1\n[s](t)\nduplex = 2\n") == []


def test_repeatable_keys_are_not_flagged():
    assert findings("[registrations]\nregister => 1:a@h\nregister => 2:b@h\n") == []


def test_repeated_macros_in_a_scheduler_stanza_are_not_flagged():
    text = (
        "[node-main](!)\nscheduler = schedule_east\n[1999](node-main)\n"
        "[schedule_east]\n85 = 00 06 * * *\n85 = 30 06 * * *\n85 = 00 07 * * *\n"
    )
    assert findings(text) == []


def test_repeated_schedule_entries_in_an_unreferenced_stanza_are_not_flagged():
    assert findings("[scheduler]\n;Time on the hour\n85=00 06 * * *\n85=30 06 * * *\n85=00 07 * * *\n") == []


def test_a_schedule_entry_repeating_a_non_schedule_value_still_warns():
    (f,) = findings("[schedule_east]\n85 = 00 06 * * *\n85 = *3\n")
    assert f.code == "duplicate_key"


def test_errors_sort_before_warnings_and_counts():
    fs_ = findings("[s]\nnope\n[x](missing)\n")
    assert [f.severity for f in fs_] == ["error", "warning"]
    assert counts(fs_) == {"error": 1, "warning": 1, "info": 0}


def test_findings_point_into_included_files():
    (f,) = findings("[g]\n#include custom/x.conf\n", **{"custom/x.conf": "[c]\na = 1\na = 2\n"})
    assert f.file == "custom/x.conf" and f.line == 3


def test_duplicate_sections_warn():
    (f,) = findings("[s]\na = 1\n[s]\nb = 2\n")
    assert f.code == "duplicate_section" and f.line == 3
