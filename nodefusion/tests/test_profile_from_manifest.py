
from __future__ import annotations

from pathlib import Path

import pytest

from nodefusion.host import kernels as K
from nodefusion.model import manifest as M


def _load(tmp_path: Path, body: str) -> M.Manifest:
    p = tmp_path / "k.toml"
    p.write_text('[kernel]\nname = "t"\n\n' + body, encoding="utf-8")
    return M.load(p)



def test_a_manifest_without_a_profile_is_not_broken(tmp_path):
    assert _load(tmp_path, "").profile is None


def test_a_half_written_profile_is_an_error(tmp_path):
    with pytest.raises(M.ManifestError, match=r"kernel_image"):
        _load(tmp_path, '[profile]\nkernel_elf = "a"\nbuild = "make"\n')


def test_the_error_says_the_other_option(tmp_path):
    with pytest.raises(M.ManifestError, match=r"整节删掉"):
        _load(tmp_path, '[profile]\nkernel_elf = "a"\n')


def test_an_unknown_key_is_rejected(tmp_path):
    with pytest.raises(M.ManifestError, match=r"kernel_elfs?"):
        _load(tmp_path, '[profile]\nkernel_elf = "a"\nkernel_image = "b"\n'
                        'build = "make"\nkernel_elfs = "typo"\n')


def test_shell_probe_takes_exactly_dir_and_ident(tmp_path):
    with pytest.raises(M.ManifestError, match=r"dir 和 ident"):
        _load(tmp_path, '[profile]\nkernel_elf = "a"\nkernel_image = "b"\n'
                        'build = "make"\n\n[profile.shell_probe]\npath = "os/src"\n')



def test_xv6_still_classifies_the_same_way():
    x = K.by_kind("xv6")
    assert x.classify("hart 1 starting\npanic: acquire\n") == "panic"
    assert x.classify("$ ") == "qemu_exited"
    assert x.booted("$ ") is True


def test_rcore_still_reads_done_before_panic():
    r = K.by_kind("rcore")
    both = ("[kernel] Panicked at src/task/mod.rs:153 "
            "All applications completed!\n")
    assert r.classify(both) == "completed"
    assert r.classify("[kernel] Panicked at src/mm/heap.rs out of memory\n") == "panic"


def test_rcore_mounts_the_block_device_only_when_the_image_exists(tmp_path):
    r = K.by_kind("rcore")
    assert not any("virtio-blk" in o for o in r.machine_args(tmp_path))
    img = tmp_path / r.devices[0].file
    img.parent.mkdir(parents=True, exist_ok=True)
    img.write_bytes(b"\0")
    assert any("virtio-blk" in o for o in r.machine_args(tmp_path))


def test_lists_from_toml_become_tuples():
    r = K.by_kind("rcore")
    for v in (r.machine_opts, r.required_tools, r.ready_markers,
              r.done_markers, r.panic_markers, r.unsupported, r.detect_files,
              r.devices, r.protect, r.devices[0].opts):
        assert isinstance(v, tuple)


def test_the_shell_probe_still_flips_rcore_to_interactive(tmp_path):
    r = K.by_kind("rcore")
    assert r.interactive is False
    src = tmp_path / "os" / "src"
    src.mkdir(parents=True)
    (src / "task.rs").write_text("lazy_static! { INITPROC }", encoding="utf-8")
    on = r.specialize(tmp_path)
    assert on.interactive is True and on.prompt == ">> "
    assert "program" not in on.unsupported


def test_a_tree_without_the_marker_stays_non_interactive(tmp_path):
    (tmp_path / "os" / "src").mkdir(parents=True)
    assert K.by_kind("rcore").specialize(tmp_path).interactive is False



def test_detect_reads_its_fingerprints_from_the_manifest(tmp_path):
    for f in K.by_kind("xv6").detect_files:
        (tmp_path / f).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / f).write_text("", encoding="utf-8")
    assert K.detect(tmp_path).kind == "xv6"


def test_an_unrecognised_tree_lists_what_each_kernel_needs(tmp_path):
    with pytest.raises(K.ProfileError) as e:
        K.detect(tmp_path)
    msg = str(e.value)
    assert "kernel/proc.h" in msg and "os/src/main.rs" in msg


def test_it_also_says_which_kernels_are_known_but_not_recordable(tmp_path):
    with pytest.raises(K.ProfileError) as e:
        K.detect(tmp_path)
    assert "还没写 [profile]" in str(e.value)


def test_asking_for_a_kernel_that_only_has_read_rules_says_so():
    name = next(iter(K.unrecordable()), None)
    if name is None:
        pytest.skip("所有 manifest 都能录了，这条没有对象可测")
    with pytest.raises(K.ProfileError) as e:
        K.by_kind(name)
    assert name in str(e.value) and "[profile]" in str(e.value)


def test_recordable_and_unrecordable_do_not_overlap():
    rec, unrec = set(K.recordable()), set(K.unrecordable())
    assert rec and unrec
    assert not (rec & unrec)


_NO_SOURCE_FINGERPRINT = frozenset({
    "axvisor",
})


def test_every_recordable_kernel_has_a_source_fingerprint():
    missing = {n for n in K.recordable() if not K.by_kind(n).detect_files}
    assert missing == set(_NO_SOURCE_FINGERPRINT)



def test_the_kernel_kind_flag_does_not_hardcode_a_choice_list():
    from nodefusion.host import cli
    a = cli.build_parser().parse_args(
        ["record", "--program", "x", "--kernel", "/nonexistent",
         "--kernel-kind", "arceos"])
    assert a.kernel_kind == "arceos"


def test_the_help_text_lists_what_can_actually_be_recorded():
    from nodefusion.host import cli
    assert set(cli._recordable_kinds()) == set(K.recordable())



def _cargo(d: Path, name: str) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    (d / "Cargo.toml").write_text(f'[package]\nname = "{name}"\n', encoding="utf-8")
    return d


def test_crate_comes_from_cargo_toml_not_from_the_directory_name(tmp_path):
    _cargo(tmp_path, "jsph-tg-arceos-tutorial-exercise-hashmap")
    p = K.by_kind("arceos", tmp_path)
    assert p.kernel_elf.endswith("/jsph-tg-arceos-tutorial-exercise-hashmap")
    assert p.kernel_image.endswith("/jsph-tg-arceos-tutorial-exercise-hashmap.bin")
    assert "{crate}" not in p.build
    assert not any("{crate}" in o for o in p.machine_opts)


def test_the_build_command_keeps_its_other_placeholder(tmp_path):
    _cargo(tmp_path, "arceos-childtask")
    assert "{mv}" not in K.by_kind("arceos", tmp_path).build
    x = K.by_kind("xv6", tmp_path)
    assert "{mv}" in x.build


def test_a_missing_cargo_toml_says_what_it_needed(tmp_path):
    with pytest.raises(K.ProfileError, match=r"Cargo\.toml"):
        K.by_kind("arceos", tmp_path)


def test_kernels_without_the_placeholder_never_read_cargo_toml(tmp_path):
    assert K.by_kind("xv6", tmp_path).kernel_elf == "kernel/kernel"



def test_arceos_attaches_the_pflash_only_when_the_image_is_there(tmp_path):
    _cargo(tmp_path, "arceos-helloworld")
    p = K.by_kind("arceos", tmp_path)
    assert not any("pflash" in o for o in p.machine_args(tmp_path))
    (tmp_path / "pflash.img").write_bytes(b"\0")
    assert any("pflash" in o for o in p.machine_args(tmp_path))


def test_a_device_entry_without_a_file_is_rejected(tmp_path):
    with pytest.raises(M.ManifestError, match=r"machine_opts"):
        _load(tmp_path, '[profile]\nkernel_elf = "a"\nkernel_image = "b"\n'
                        'build = "make"\n\n[[profile.device]]\nopts = ["-x"]\n')



def test_xv6_protects_its_fs_image_even_though_it_is_mandatory(tmp_path):
    assert tmp_path / "fs.img" in K.by_kind("xv6").protected(tmp_path)


def test_optional_device_images_are_protected_too(tmp_path):
    got = {p.name for p in K.by_kind("rcore").protected(tmp_path)}
    assert "fs.img" in got


def test_protected_paths_do_not_repeat(tmp_path):
    ps = K.by_kind("rcore").protected(tmp_path)
    assert len(ps) == len(set(ps))




def _dev_profile(tmp_path: Path, built_when: str = "") -> M.Manifest:
    return _load(tmp_path,
                 '[profile]\nkernel_elf = "os"\nkernel_image = "os.bin"\n'
                 'build = "make"\n\n[[profile.device]]\n'
                 'file = "img/fs.img"\nopts = ["-drive"]\n' + built_when)


def test_a_device_without_built_when_is_always_expected(tmp_path):
    p = K.KernelProfile.from_spec("t", _dev_profile(tmp_path).profile)
    assert p.builds(p.devices[0], tmp_path) is True
    assert tmp_path / "img/fs.img" in p.required_after_build(tmp_path)


def test_a_device_whose_probe_fails_is_not_expected_but_is_still_protected(tmp_path):
    (tmp_path / "Makefile").write_text("all:\n\techo hi\n", encoding="utf-8")
    p = K.KernelProfile.from_spec(
        "t", _dev_profile(
            tmp_path,
            'built_when = { file = "Makefile", contains = "fs-img" }\n').profile)

    assert p.builds(p.devices[0], tmp_path) is False
    assert tmp_path / "img/fs.img" not in p.required_after_build(tmp_path)
    assert tmp_path / "img/fs.img" in p.protected(tmp_path)


def test_a_device_whose_probe_passes_is_expected(tmp_path):
    (tmp_path / "Makefile").write_text("fs-img:\n\t@true\n", encoding="utf-8")
    p = K.KernelProfile.from_spec(
        "t", _dev_profile(
            tmp_path,
            'built_when = { file = "Makefile", contains = "fs-img" }\n').profile)

    assert p.builds(p.devices[0], tmp_path) is True
    assert tmp_path / "img/fs.img" in p.required_after_build(tmp_path)


def test_an_unreadable_probe_means_it_will_be_built(tmp_path):
    p = K.KernelProfile.from_spec(
        "t", _dev_profile(
            tmp_path,
            'built_when = { file = "no-such-file", contains = "x" }\n').profile)
    assert p.builds(p.devices[0], tmp_path) is True


def test_protect_entries_are_unconditional(tmp_path):
    m = _load(tmp_path, '[profile]\nkernel_elf = "os"\nkernel_image = "b"\n'
                        'build = "make"\nprotect = ["seed.img"]\n')
    p = K.KernelProfile.from_spec("t", m.profile)
    assert p.required_after_build(tmp_path) == (tmp_path / "seed.img",)


def test_built_when_survives_placeholder_substitution(tmp_path):
    (tmp_path / "Cargo.toml").write_text('[package]\nname = "os"\n',
                                         encoding="utf-8")
    (tmp_path / "Makefile").write_text("all:\n", encoding="utf-8")
    m = _load(tmp_path,
              '[profile]\nkernel_elf = "target/{crate}"\n'
              'kernel_image = "b"\nbuild = "make"\n\n[[profile.device]]\n'
              'file = "img/{crate}.img"\nopts = ["-drive"]\n'
              'built_when = { file = "Makefile", contains = "fs-img" }\n')
    p = K.KernelProfile.from_spec("t", m.profile).specialize(tmp_path)

    assert p.devices[0].file == "img/os.img"
    assert p.devices[0].built_when == ("Makefile", "fs-img")
    assert p.builds(p.devices[0], tmp_path) is False


def test_a_malformed_built_when_is_rejected_at_load(tmp_path):
    with pytest.raises(M.ManifestError, match=r"built_when"):
        _dev_profile(tmp_path, 'built_when = { file = "Makefile" }\n')
    with pytest.raises(M.ManifestError, match=r"built_when"):
        _dev_profile(tmp_path, 'built_when = "Makefile"\n')
    with pytest.raises(M.ManifestError, match=r"built_when"):
        _dev_profile(tmp_path,
                     'built_when = { file = "M", contains = "x", extra = 1 }\n')


def test_rcore_asks_the_makefile_not_the_chapter_number(tmp_path):
    p = K.by_kind("rcore", tmp_path)
    dev = next(d for d in p.devices if d.file.endswith("fs.img"))
    assert dev.built_when == ("os/Makefile", "fs-img")

    mk = tmp_path / "os"
    mk.mkdir()
    (mk / "Makefile").write_text("all:\n\t@true\n", encoding="utf-8")
    assert p.builds(dev, tmp_path) is False

    (mk / "Makefile").write_text("fs-img:\n\t@make -C ../user build\n",
                                 encoding="utf-8")
    assert p.builds(dev, tmp_path) is True



def _prof(opts) -> K.KernelProfile:
    return K.KernelProfile(
        kind="t", kernel_elf="e", kernel_image="i", build="b",
        detect_files=(), required_tools=(), machine_opts=tuple(opts),
        interactive=False)


@pytest.mark.parametrize("opts, want", [
    (["-m 512M"],                     512 << 20),
    (["-m 1024M"],                   1024 << 20),
    (["-m 128M"],                     128 << 20),
    (["-m 1G"],                      1024 << 20),
    (["-m 4g"],                      4096 << 20),
    (["-m 512"],                      512 << 20),
    (["-m", "512M"],                  512 << 20),
    (["-m size=512M,slots=2"],        512 << 20),
    (["-M virt", "-m 2G", "-bios default"], 2048 << 20),
])
def test_ram_is_read_off_the_machine_options(opts, want):
    n, why = _prof(opts).ram_bytes()
    assert (n, why) == (want, "")


@pytest.mark.parametrize("opts, needle", [
    ([],                "没有 -m"),
    (["-m abc"],        "不是整数"),
    (["-m 0"],          "不是个合法"),
    (["-m slots=2"],    "没有 size="),
])
def test_unreadable_ram_says_why_instead_of_guessing(opts, needle):
    n, why = _prof(opts).ram_bytes()
    assert n is None
    assert needle in why


def test_the_real_manifests_declare_more_ram_than_the_plugin_default():
    from nodefusion.model.manifest import load_dir

    plug = 128 << 20
    mans, got = load_dir(), {}
    for kind in ("alien", "starry", "arceos", "rcore", "xv6"):
        n, why = K.KernelProfile.from_spec(kind, mans[kind].profile).ram_bytes()
        assert n is not None, f"{kind}: {why}"
        got[kind] = n
    assert got["alien"] > plug and got["starry"] > plug
    assert got["arceos"] == got["rcore"] == got["xv6"] == plug
