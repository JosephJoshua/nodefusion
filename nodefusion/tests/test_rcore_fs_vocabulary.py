
from __future__ import annotations

from pathlib import Path

import pytest

from nodefusion.tests.kernelelf import elf_or_skip

MANIFEST = (Path(__file__).resolve().parents[2]
            / "nodefusion/manifests/rcore.toml")

MAPPED = {
    "easy_fs::vfs::Inode::read_at": "inode.read",
    "easy_fs::vfs::Inode::write_at": "inode.write",
    "easy_fs::layout::DiskInode::get_block_id": "inode.bmap",
    "easy_fs::vfs::Inode::find_inode_id": "inode.dirlookup",
    "easy_fs::efs::EasyFileSystem::alloc_inode": "inode.alloc",
    "easy_fs::efs::EasyFileSystem::alloc_data": "disk.balloc",
    "easy_fs::efs::EasyFileSystem::dealloc_data": "disk.bfree",
}

UNMAPPED = {
    "easy_fs::bitmap::Bitmap::alloc":
        "EasyFileSystem::alloc_inode / alloc_data 已经把两个角色分开映了，"
        "this layer would count the same allocation twice",
    "easy_fs::bitmap::Bitmap::dealloc":
        "dealloc_data is already mapped to disk.bfree",
    "easy_fs::layout::DiskInode::read_at":
        "mapping this below Inode::read_at would count the same read twice",
    "easy_fs::vfs::Inode::create":
        "composite action; mapping it would duplicate inode.alloc",
}


def _elf_or_skip() -> Path:
    return elf_or_skip("rcore")


def _entries():
    from nodefusion.host.nfelf import Elf64
    from nodefusion.host.record import select_watchlist
    elf = _elf_or_skip()
    wl, _, _ = select_watchlist(Elf64(str(elf)), elf, kind="rcore")
    return {e.symbol: e for e in wl.entries}


@pytest.mark.parametrize("symbol,kind", sorted(MAPPED.items()))
def test_the_four_inode_functions_really_carry_their_kind(symbol, kind):
    by_sym = _entries()
    e = by_sym.get(symbol)
    assert e is not None, (
        f"{symbol} 压根不在观察点里 —— manifest 里那条映射是死的。"
        f"多半是 [[watch]] 的 module 名单没覆盖到它")
    assert e.kind == kind, (
        f"{symbol} 的类别是 {e.kind!r}，期望 {kind!r}")


@pytest.mark.parametrize("symbol,why", sorted(UNMAPPED.items()))
def test_the_look_alikes_stay_unmapped(symbol, why):
    by_sym = _entries()
    e = by_sym.get(symbol)
    assert e is not None, (
        f"{symbol} 不在观察点里了。这条测试要的是「挂着但没类别」，"
        f"现在连观察点都没有，说明 [[watch]] 规则变窄了 —— "
        f"那是另一个问题，但也得有人看见")
    assert not e.kind, (
        f"{symbol} 被映成了 {e.kind!r}。不该映：{why}")


def test_the_manifest_records_why_each_look_alike_is_left_alone():
    text = MANIFEST.read_text(encoding="utf-8")
    for symbol in UNMAPPED:
        short = symbol.rsplit("::", 1)[-1]
        assert short in text, f"manifest 里没提 {symbol}，不映的理由无处可查"
    for token in ("start_block_id",
                  "balloc",
                  "ialloc",
                  "log / journal",
                  "dealloc_inode",
                  "counted twice"):
        assert token in text, f"manifest is missing evidence token {token!r}"


def test_why_the_unwatchable_claim_was_wrong_stays_written_down():
    text = MANIFEST.read_text(encoding="utf-8")
    for symbol in ("alloc_inode", "alloc_data", "dealloc_data"):
        assert symbol in text, (
            f"manifest 里没提 {symbol} —— 这三条是 rCore 上区分 inode 分配和"
            f"数据块分配的唯一办法，删掉它们等于把 disk.balloc 又变成不可达")
    assert "select_watchlist" in text, (
        "manifest 里不再提 select_watchlist —— 那是「当初凭什么判错」的正主。"
        "没有它，下次有人发现这几个函数没符号，会照着同一条错路再走一遍")


def test_log_commit_is_absent_by_design_not_merely_unmapped():
    text = MANIFEST.read_text(encoding="utf-8")
    assert '= "log.commit"' not in text, (
        "rCore 的 manifest 里出现了 log.commit 映射。easy-fs 没有日志，"
        "最像的 block_cache_sync_all 只是写回脏块、不保证原子性 —— "
        "映了等于替 rCore 声称了一个它没有的崩溃保证")
    assert "block_cache_sync_all" in text, (
        "manifest 里不再提 block_cache_sync_all —— 那是「为什么不映」的正主，"
        "没有它，下一个人只会看见一个没解释的空缺")
