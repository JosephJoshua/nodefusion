# NodeFusion

NodeFusion 记录 QEMU 中运行的操作系统内核，生成可离线打开的交互报告。报告包含事件时间线、进程与资源状态、函数轨迹和两次运行的对比。内核结构和函数映射写在 manifest 中；需要操作结果时，可以加入内核侧 `nftrace` 探针。

支持 xv6-riscv、rCore、ArceOS、StarryOS 和 uCoreOS。[运行报告](artifacts/)按内核存放。

## 开始使用

需要 Python 3.11+、支持 TCG plugin 的 `qemu-system-riscv64`，以及目标内核的编译工具链。从仓库根目录执行：

```bash
make -C nodefusion/plugin
python -m nodefusion.host.cli doctor
```

QEMU 安装在其他位置时，构建命令可加 `NF_QEMU_PREFIX=/path/to/qemu`。macOS 默认查找 `/opt/homebrew`，Linux/WSL 默认查找 `/opt/qemu-nf`。

以下示例需要一份本地 xv6-riscv 源码。`--kernel` 指向它的工程目录。macOS 上编译 xv6 时，确保 `gcc` 指向 GNU GCC；可以先用 `doctor` 检查工具链。

```bash
python -m nodefusion.host.cli record \
  --kernel /path/to/xv6-riscv \
  --kernel-kind xv6 \
  --program cowtest \
  --name xv6-cow
```

录制结束后，打开 `nodefusion/runs/xv6-cow/xv6-cow.html`。运行目录还包含原始轨迹 `trace.nfb`、串口输出 `console.log`、本次构建的布局和观察点记录。需要函数返回事件和调用链时，在录制命令中加 `--function-returns`。

已有录制可以重新渲染、审计或与另一趟运行对比：

```bash
python -m nodefusion.host.cli render --run xv6-cow
python -m nodefusion.host.cli audit --run xv6-cow --json
python -m nodefusion.host.cli compare \
  --run xv6-cow-before --run xv6-cow-after -o compare.html
```

`events.jsonl` 是可选的完整事件流。默认模式会在预计超过 256 MiB 或磁盘空间不足时跳过导出；需要该文件时传入 `--event-stream always`。HTML 为浏览保留最多 150,000 条事件，事件数量和抽样情况写在报告中。

## 文档

- [添加内核支持](docs/manifests/AUTHORING.md)
- [Manifest 语法参考](docs/manifests/REFERENCE.md)
- [内核侧观测补丁](nodefusion/integrations/README.md)
- [事件流与轨迹格式](nodefusion/spec/event-stream.md)
- [源码目录](nodefusion/README.md)

## 测试

```bash
python -m pytest nodefusion/tests -q
```

运行本机录制语料时加 `--run-corpus`；完整扫描大轨迹时设置 `NF_CORPUS_MAX_TRACE_MIB=0`。

## 项目来源

本项目构建在兰州大学参赛项目 NodeFusion 的基础上。原项目由“都可以对”队伍（ID：`T2026107309910864`）完成，题目为中国计算机系统能力大赛操作系统功能挑战赛道 `proj54`“面向操作系统课程的操作系统竞赛和实验”。

代码采用 [MIT 许可证](LICENSE)。
