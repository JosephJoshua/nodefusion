
import pytest

from nodefusion.model import manifest as M
from nodefusion.model.kinds import UnknownKindError
from nodefusion.model.manifest import EventSpec
from nodefusion.host.watchlist import _pick_branch


class _FakeDw:

    def __init__(self, types=()):
        self._types = set(types)

    def find(self, name):
        return object() if name in self._types else None


def _toml(tmp_path, body: str):
    p = tmp_path / "k.toml"
    p.write_text("[kernel]\nname = \"k\"\nfamily = \"k\"\n"
                 "arches = [\"riscv64\"]\n" + body, encoding="utf-8")
    return p


_TWO_BRANCH = '''
[event]
"pkg::Task::new" = [
  { kind = "thread.create", when = { type_exists = "pkg::Process" } },
  { kind = "proc.create" },
]
'''



def test_a_candidate_list_parses_into_a_head_plus_alts(tmp_path):
    m = M.load(_toml(tmp_path, _TWO_BRANCH))
    s = m.events["pkg::Task::new"]
    assert s.kind == "thread.create"
    assert s.when == {"type_exists": "pkg::Process"}
    assert [a.kind for a in s.alts] == ["proc.create"]
    assert s.alts[0].when is None


def test_the_last_candidate_must_be_unconditional(tmp_path):
    body = '''
[event]
"pkg::Task::new" = [
  { kind = "thread.create", when = { type_exists = "pkg::Process" } },
  { kind = "proc.create", when = { type_exists = "pkg::Other" } },
]
'''
    with pytest.raises(M.ManifestError, match="兜底"):
        M.load(_toml(tmp_path, body))


def test_an_unconditional_candidate_before_the_end_is_refused(tmp_path):
    body = '''
[event]
"pkg::Task::new" = [
  { kind = "proc.create" },
  { kind = "proc.exec" },
]
'''
    with pytest.raises(M.ManifestError, match="永远轮不上"):
        M.load(_toml(tmp_path, body))


def test_an_empty_candidate_list_is_refused(tmp_path):
    with pytest.raises(M.ManifestError, match="空表"):
        M.load(_toml(tmp_path, '[event]\n"pkg::Task::new" = []\n'))


def test_every_branch_gets_its_kind_checked(tmp_path):
    body = '''
[event]
"pkg::Task::new" = [
  { kind = "thread.create", when = { type_exists = "pkg::Process" } },
  { kind = "nosuch.kind" },
]
'''
    with pytest.raises(UnknownKindError, match="第 2 条候选"):
        M.load(_toml(tmp_path, body))



def test_the_conditional_branch_wins_when_the_type_is_there():
    spec = EventSpec(kind="thread.create",
                     when={"type_exists": "pkg::Process"},
                     alts=(EventSpec(kind="proc.create"),))
    assert _pick_branch(_FakeDw({"pkg::Process"}), spec).kind == "thread.create"


def test_the_fallback_wins_when_it_is_not():
    spec = EventSpec(kind="thread.create",
                     when={"type_exists": "pkg::Process"},
                     alts=(EventSpec(kind="proc.create"),))
    assert _pick_branch(_FakeDw(), spec).kind == "proc.create"


def test_a_plain_spec_never_touches_dwarf():
    class _Explodes:
        def find(self, name):
            raise AssertionError("不该查 DWARF")

    spec = EventSpec(kind="proc.create")
    assert _pick_branch(_Explodes(), spec) is spec



def test_rcore_maps_task_new_by_structure_not_by_chapter():
    m = M.load_dir(M.builtin_dir())["rcore"]
    spec = m.events["os::task::task::TaskControlBlock::new"]
    ch8 = _FakeDw({"os::task::process::ProcessControlBlock"})
    assert _pick_branch(ch8, spec).kind == "thread.create"
    assert _pick_branch(_FakeDw(), spec).kind == "proc.create"


def test_no_rcore_event_key_mentions_a_chapter():
    import re
    m = M.load_dir(M.builtin_dir())["rcore"]
    bad = [k for k in m.events if re.search(r"\bch[1-9]\b", k)]
    assert not bad, bad
    conds = [w for s in m.events.values()
             for w in ((s.when,) + tuple(a.when for a in s.alts)) if w]
    assert conds, "rcore 里一条带 when 的都没有，这条测试没验证到东西"
    for w in conds:
        assert not re.search(r"\bch[1-9]\b", repr(w)), w
