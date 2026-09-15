
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from nodefusion.model import manifest as M                    # noqa: E402

DRAFTS = Path(__file__).resolve().parents[1] / "manifests"


def _mk(*entities) -> M.Manifest:
    return M.Manifest(name="t", entities=[
        M.EntitySpec(name=n, type="T", role=r) for n, r in entities])


def test_role_wins_over_the_name():
    m = _mk(("process", "process"), ("task", ""))
    assert m.entity_for("process", fallback="task").name == "process"


def test_falls_back_to_the_name_when_no_role_is_declared():
    m = _mk(("task", ""))
    assert m.entity_for("process", fallback="task").name == "task"


def test_returns_none_rather_than_picking_something():
    m = _mk(("vm", ""), ("vcpu", ""))
    assert m.entity_for("process", fallback="task") is None


def test_every_draft_manifest_declares_the_role_itself():
    for p in sorted(DRAFTS.glob("*.toml")):
        m = M.load(p)
        by_role = m.entity_for("process")
        by_name = m.entity_for("process", fallback="task")
        assert by_role is by_name, (
            f"{p.name}：靠名字兜底才找到 {by_name.name!r}，"
            f"应当在 [[entity]] 上写 role = \"process\"")


def test_hypervisor_manifests_say_so_instead_of_showing_an_empty_table():
    ax = DRAFTS / "axvisor.toml"
    if not ax.exists():
        return
    m = M.load(ax)
    assert m.entity_for("process", fallback="task") is None
    assert [e.name for e in m.entities], "axvisor 应该至少有 vm 这类实体"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
