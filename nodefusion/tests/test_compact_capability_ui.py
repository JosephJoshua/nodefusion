"""Capability caveats stay available without occupying the report viewport."""

from pathlib import Path


ASSETS = Path(__file__).resolve().parents[1] / "host" / "assets"


def test_capability_details_are_collapsed_by_default():
    js = (ASSETS / "app.js").read_text(encoding="utf-8")
    assert "el('details', 'cap-disclosure')" in js
    assert ".open = true" not in js
    assert "100% 可适用覆盖" in js


def test_long_unobservable_reason_is_an_expandable_detail():
    js = (ASSETS / "app.js").read_text(encoding="utf-8")
    assert "el('details', 'inline-disclosure hint')" in js
    assert "为什么有指标显示“—”" in js


def test_missing_rules_are_summarized_by_count_before_the_detail():
    js = (ASSETS / "app.js").read_text(encoding="utf-8")
    assert "未匹配观察规则 ${num(c.missing_watch_functions.length)} 条" in js


def test_optional_field_explanations_are_collapsed_by_default():
    js = (ASSETS / "app.js").read_text(encoding="utf-8")
    assert "`未显示的可选字段（${dropped.length}）`" in js
    assert "d.appendChild(el('div', 'disclosure-body'" in js
