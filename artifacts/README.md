# NodeFusion artifacts

每个内核一个目录，里面同时放浏览器可打开的 HTML 报告、审计 JSON/MP4
证据和对应索引。HTML 是自包含的，不依赖任何外部文件。

## 有哪些

| 内核 | manifest | 产物目录 | 说明 |
|------|----------|-----------|------|
| xv6-riscv | `xv6.toml` | [`xv6/`](xv6/) | 3 份，早期版本产物，见该目录 README |
| rCore | `rcore.toml` | [`rcore/`](rcore/) | 2 份，当前版本，其中一份是内核 panic 的运行 |
| ArceOS | `arceos.toml` | [`arceos/`](arceos/) | 1 份，当前版本，事件很少（原因见该目录 README） |
| StarryOS | `starry.toml` | [`starryos/`](starryos/) | 严格 100% 适用项录制的证据索引；原始轨迹不进 Git |
| uCoreOS | `ucore.toml` | [`ucoreos/`](ucoreos/) | ch1–ch8 的覆盖矩阵与归档报告索引 |
| AxVisor | `axvisor.toml` | 暂无 | 同上 |
| reL4 | `rel4.toml` | 暂无 | 同上 |
| Alien | `alien.toml` | 暂无 | 同上 |

StarryOS 的最终录制已完成，但没有把 837 MiB 的原始轨迹伪装成源码样例提交进 Git；
它与 rCore ch7 最终录制保存在独立归档中，并由 SHA-256 清单校验。uCoreOS 的八章
覆盖矩阵也有单独索引。AxVisor、reL4、Alien 仍然没有样例目录；有 manifest 不等于
有测量数据，空目录会让人以为录过了。

## 自己生成一份

录制需要对应内核的源码树，`--kernel` 指到那儿：

```bash
python -m nodefusion.host.cli record --kernel <内核源码目录> --name <运行名>
python -m nodefusion.host.cli render --run <运行名> -o out.html
```

两次运行的对比报告（`xv6/lab3-cow/compare-cow.html` 就是这么来的）：

```bash
python -m nodefusion.host.cli compare --run <运行A> --run <运行B> -o compare.html
```

录制产物落在 `nodefusion/runs/`，不进 git —— 一趟录制只有配上录它时那份内核
二进制才解得开，换台机器得重录。所以这里放的是**渲染完的 HTML**，不是原始
trace。

## 关于 manifest.json

每个样例目录里那份 `manifest.json` 是录制时的现场记录：内核路径、QEMU 命令行、
插件参数、ELF 指纹。rCore 和 ArceOS 这两份里的本机 home 路径换成了 `$HOME`，
文件里有 `path_redaction` 字段写明了这件事；其余字段与 `runs/` 里的原件逐字一致。

## 审计证据

这些 MP4 是录制运行的逐帧导出，不是屏幕录制。每个视频都有同名 JSON sidecar，
包含完整 ELF SHA-256、观测字段、工作负载、快照和事件计数、视频元数据以及 MP4
SHA-256。

`starryos/` contains three actual workloads against the archived ELF. The showcase
run contains 3,013,733 decoded events; the interactive report retains 150,000 under
the documented sampling policy while metrics use the full raw stream. `rcore/`
contains chapter-specific recordings from ch1 through ch8. Each
`ucoreos/chN/coverage.json` records the archived report hashes for that chapter.

Rebuild evidence from an immutable run directory with:

```sh
python -m nodefusion.host render --run starry-showcase-exact
python -m nodefusion.host video --run starry-showcase-exact \
  --section all --fps 12 --width 1280 --height 720 \
  --copy-to artifacts/starryos

python -m nodefusion.host render --run rcore-ch8-exact-filetest
python -m nodefusion.host video --run rcore-ch8-exact-filetest \
  --fps 12 --width 1280 --height 720 \
  --copy-to artifacts/rcore
```

The source runs and archived ELFs remain outside Git because they are large; the
committed MP4s, JSON sidecars, and coverage matrix are the portable review artifacts.
