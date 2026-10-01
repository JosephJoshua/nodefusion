"""Capability caveats stay available without occupying the report viewport."""

from pathlib import Path


ASSETS = Path(__file__).resolve().parents[1] / "host" / "assets"


def test_capability_details_are_collapsed_by_default():
    js = (ASSETS / "app.js").read_text(encoding="utf-8")
    assert "el('details', 'cap-disclosure')" in js
    assert ".open = true" not in js
    assert "观测项 ${metric.covered}/${metric.applicable}" in js
    assert "for (const n of run.meta.notes || [])" not in js


def test_long_unobservable_reason_is_an_expandable_detail():
    js = (ASSETS / "app.js").read_text(encoding="utf-8")
    assert "el('details', 'inline-disclosure hint')" in js
    assert "el('summary', null, '指标不可用')" in js


def test_missing_rules_are_summarized_by_count_before_the_detail():
    js = (ASSETS / "app.js").read_text(encoding="utf-8")
    assert "未匹配的函数观察点 ${num(c.missing_watch_functions.length)} 个" in js


def test_optional_field_explanations_are_collapsed_by_default():
    js = (ASSETS / "app.js").read_text(encoding="utf-8")
    assert "`未显示的可选字段（${dropped.length}）`" in js
    assert "d.appendChild(el('div', 'disclosure-body'" in js


def test_primary_copy_uses_compact_unknown_states():
    js = (ASSETS / "app.js").read_text(encoding="utf-8")
    assert "画成 0 会让人误以为没发生过" not in js
    assert "const shortText =" in js
    assert "p.appendChild(el('div', 'hint', '无观测点'))" in js


def test_report_has_global_find_and_collapsed_secondary_filters():
    js = (ASSETS / "app.js").read_text(encoding="utf-8")
    assert "function submitQuickFind(query)" in js
    assert "const pid = /^pid" in js
    assert "const insn = /^#" in js
    assert "el('details', 'advanced-filters')" in js
    assert "NF.functionFilters.text = e.entryName || e.func || ''" in js


def test_mobile_detail_is_closable_without_scrolling_to_page_end():
    css = (ASSETS / "app.css").read_text(encoding="utf-8")
    assert "position: fixed; z-index: 20; inset: 0" in css
    assert "height: 100dvh" in css
    assert ".debugger[data-mobile-view=source] .debug-stack" in css
    assert ".right:has(.detail-empty) { display: none; }" in css
