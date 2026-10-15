"""The lossless line model and Asterisk's lexing rules."""

from hypothesis import given, settings
from hypothesis import strategies as st

from asl_web_ui.configengine.text import ConfigText, strip_comments


def kinds(text):
    return [(l.kind, l.name or l.key or l.directive, l.value) for l in ConfigText.from_text(text).lines]


@settings(max_examples=300)
@given(st.binary(max_size=400))
def test_any_bytes_round_trip(data):
    assert ConfigText(data).to_bytes() == data


@settings(max_examples=300)
@given(st.lists(st.sampled_from([
    "[general]", "[1999](node-main)", "[t](!)", "key = value", "key=>value", "k += more",
    "; comment", "  ", "", "a = b ; trailing", r"x = semi\;colon", ";-- block", "inside", "--;",
    "#include foo.conf", "#tryinclude \"custom/*.conf\"", "no equals here", "\t[spaced]  ",
]), max_size=30), st.sampled_from(["\n", "\r\n"]), st.booleans())
def test_config_like_text_round_trips(lines, nl, final_newline):
    text = nl.join(lines) + (nl if final_newline else "")
    assert ConfigText.from_text(text).to_text() == text


def test_invalid_utf8_preserved():
    data = b"[general]\nname = caf\xe9\n"
    assert ConfigText(data).to_bytes() == data


def test_bom_ignored_for_lexing():
    assert kinds("﻿[general]\n")[0][:2] == ("section", "general")


def test_sections_and_options():
    lines = ConfigText.from_text("[1999](node-main,shari)\n[t](!)\n[bad\n[x](a\n").lines
    assert (lines[0].name, lines[0].options) == ("1999", ["node-main", "shari"])
    assert lines[1].options == ["!"]
    assert lines[2].header_error == "no closing ']'"
    assert lines[3].header_error == "no closing ')'"


def test_variables_and_operators():
    lines = ConfigText.from_text("a = 1\nb => 2\nc += 3\n" r"\;x = 4" "\nnope\n").lines
    assert [(l.key, l.operator, l.value) for l in lines[:3]] == [("a", "=", "1"), ("b", "=>", "2"), ("c", "+=", "3")]
    # Asterisk removes the "\;" escape before it looks for a leading backslash.
    assert lines[3].key == ";x" and not lines[3].escaped_name
    escaped = ConfigText.from_text(r"\#x = 1" "\n").lines[0]
    assert escaped.kind == "variable" and escaped.key == "#x" and escaped.escaped_name
    assert lines[4].kind == "invalid"


def test_inline_and_escaped_comments():
    line = ConfigText.from_text("idrecording = |iN0CALL   ; the ID\n").lines[0]
    assert line.value == "|iN0CALL" and line.text[line.comment_at] == ";"
    line = ConfigText.from_text(r"x = a\;b ; c" "\n").lines[0]
    assert line.value == "a;b" and line.text[line.comment_at] == ";" and not line.simple


def test_block_comments_span_lines():
    text = "[g]\na = 1 ;-- start\nb = 2\nend --; c = 3\nd = 4\n"
    got = [(l.kind, l.key) for l in ConfigText.from_text(text).lines]
    assert got == [("section", ""), ("variable", "a"), ("comment", ""), ("variable", "c"), ("variable", "d")]


def test_line_with_block_inside():
    assert strip_comments("a ;-- x --; b", 0).content == "a  b"


def test_stray_block_end_hides_rest_of_file():
    text = "[g]\na = 1\nb = 2 --;\nc = 3\nd = 4\n"
    ct = ConfigText.from_text(text)
    assert ct.lines[2].stray_block_end
    # Asterisk keeps the stray line itself, then ignores everything after it.
    assert [l.kind for l in ct.lines[3:]] == ["comment", "comment"]


def test_directives():
    lines = ConfigText.from_text('#include "custom/rpt.conf"\n#tryinclude <custom/rpt/*.conf>\n#bogus x\n#include\n').lines
    assert [(l.directive, l.argument) for l in lines] == [
        ("include", "custom/rpt.conf"), ("tryinclude", "custom/rpt/*.conf"), ("bogus", "x"), ("include", None)]


def test_newline_style():
    assert ConfigText.from_text("a\r\nb\r\n").newline == "\r\n"
    assert ConfigText.from_text("a\nb\n").newline == "\n"
