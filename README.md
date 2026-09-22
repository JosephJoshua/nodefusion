# NodeFusion

NodeFusion 是一个面向操作系统内核实验的外部运行观测工具。它在 QEMU 进程中加载
TCG 插件，从虚拟机外部记录指令、寄存器、异常、函数入口和物理内存快照；Python
分析器再把这些原始数据重建为统一事件流、系统状态和自包含的 HTML 报告。

```text
QEMU + TCG plugin -> trace.nfb -> Python analysis -> self-contained HTML
```

基础观测通过 QEMU 外部完成。函数入口无法表达返回值、提交结果或调度决定时，
对应内核的 `nftrace` 集成补丁会补充这些语义；相关字段按可验证数据填写，无法
确认时标为 `unknown`。

## 项目来源与致谢

本项目构建在兰州大学参赛项目 NodeFusion 的基础上。项目信息如下：

| 项目 | 信息 |
| --- | --- |
| 学校 | 兰州大学 |
| 队伍 ID | `T2026107309910864` |
| 队伍名 | 都可以对 |
| 题目编号 | `proj54` |
| 题目名称 | 面向操作系统课程的操作系统竞赛和实验（中国计算机系统能力大赛操作系统功能挑战赛道） |
| 项目名称 | NodeFusion |

## 当前支持

支持矩阵按公开样例和可复核覆盖证据维护。`nodefusion/manifests/` 中的其他文件
用于实验性配置。

| 内核 | Manifest | 已提交的材料 | 当前状态 |
| --- | --- | --- | --- |
| xv6-riscv | [`xv6.toml`](nodefusion/manifests/xv6.toml) | [`artifacts/xv6`](artifacts/xv6) | 启动、lazy allocation、COW 对比样例；样例来自较早的录制 |
| rCore | [`rcore.toml`](nodefusion/manifests/rcore.toml) | [`artifacts/rcore`](artifacts/rcore) | ch1--ch8 均通过严格适用项审计 |
| ArceOS | [`arceos.toml`](nodefusion/manifests/arceos.toml) | [`artifacts/arceos`](artifacts/arceos) | 四个应用的报告；当前录制存在覆盖缺项 |
| StarryOS | [`starry.toml`](nodefusion/manifests/starry.toml) | [`artifacts/starryos`](artifacts/starryos) | 子系统和应用证据；严格审计达到 100% 适用项覆盖 |
| uCoreOS | [`ucore.toml`](nodefusion/manifests/ucore.toml) | [`artifacts/ucoreos`](artifacts/ucoreos) | Tutorial ch1--ch8 每章均有 100% 适用项覆盖记录 |

“100%”指当前内核构建和 workload 下的适用项全部通过审计，记录见
[StarryOS showcase](artifacts/starryos/showcase/starry-100pct-final.evidence.json)、
[rCore ch7](artifacts/rcore/ch7/rcore-ch7-100pct-final.evidence.json)
和 [uCoreOS 各章的 coverage.json](artifacts/ucoreos)。每个声明项按适用性记录；
内核未提供对应机制时，
该项标为 `not applicable`。例如 rCore 和 uCoreOS 的文件系统未提供日志层，
`log.commit` 在它们的覆盖结果中标为 `not applicable`。

StarryOS 的 showcase 原始流包含 6,659,153 条事件；交互式报告按文档化策略保留
150,000 条用于浏览，覆盖率和统计使用完整原始流。原始 `trace.nfb` 保存在归档中，
仓库中的 JSON sidecar、MP4 和覆盖索引用于复核产物范围与校验和。

rCore ch1--ch8、StarryOS 的两个应用及 ArceOS tracecomplete 的报告
包含返回指令核对的观测调用链；其他旧报告仍只有入口和直接调用方。

## 快速开始

可以先打开仓库中的 [xv6 启动报告](artifacts/xv6/boot/boot-trace.html) 查看交互式
时间轴。下面的步骤用于自己录制一趟。

### 环境

- Python 3.11 或更新版本
- 带 TCG plugin 支持的 QEMU（需要 `qemu-system-riscv64`）
- 目标内核自己的编译工具链，例如 Rust 内核需要 `cargo`
- `gcc`（xv6 的宿主工具需要）
- `ffmpeg` 和 Chromium/Chrome（只在导出 MP4 时需要）

从源码运行，Python 直接使用仓库代码：

```bash
git clone https://github.com/JosephJoshua/nodefusion.git
cd nodefusion
python3 -m venv .venv
. .venv/bin/activate
python -m nodefusion.host.cli doctor
```

在 macOS 上，插件默认从 `/opt/homebrew` 查找 QEMU；在 Linux/WSL 上默认从
`/opt/qemu-nf` 查找。通过 `NF_QEMU_PREFIX` 可以指定其他前缀：

```bash
NF_QEMU_PREFIX=/path/to/qemu make -C nodefusion/plugin
```

使用默认前缀构建：

```bash
make -C nodefusion/plugin
```

### 录制、渲染和审计

`--kernel` 指向目标内核源码树。目录特征文件可以自动选择 manifest；识别结果有
歧义时显式传入 manifest 名称：

```bash
python -m nodefusion.host.cli record \
  --kernel ~/src/xv6-riscv \
  --kernel-kind xv6 \
  --program cowtest \
  --name xv6-cow

python -m nodefusion.host.cli render --run xv6-cow
python -m nodefusion.host.cli audit --run xv6-cow --json
```

`record` 默认在运行结束后渲染 HTML。单独使用 `render` 时，报告写入运行目录；
也可以用 `-o` 指定路径。两次运行可以生成并排对比报告：

```bash
python -m nodefusion.host.cli compare \
  --run xv6-cow-off \
  --run xv6-cow-on \
  -o compare-cow.html
```

运行目录位于 `nodefusion/runs/<name>/`，已加入 Git ignore。录制时使用的 ELF 会按
SHA-256 归档到 `nodefusion/kernels/`；两个目录共同保留一趟运行所需的数据。重要
文件如下：

| 文件 | 作用 |
| --- | --- |
| `trace.nfb` | 插件写入的原始二进制轨迹，分析的权威输入 |
| `<name>.html` | 自包含、可离线打开的交互式报告 |
| `manifest.json` | 本次运行的内核、构建、QEMU、快照和结局信息 |
| `kernel_layout.json` | 从目标 ELF/DWARF 和编译期探针得到的布局 |
| `watchlist.txt` / `watchlist.json` | 选中的观察点及目标 ELF 中缺失的符号 |
| `events.jsonl` | 可选的统一事件流导出 |
| `console.log` | guest 串口原始输出 |

`events.jsonl` 默认使用 `--event-stream auto`：预计超过 256 MiB 或磁盘余量不足
时省略 JSONL，HTML 先安全写完。需要完整 JSONL 时使用
`--event-stream always`；只需要报告时使用 `--no-event-stream`。

### 导出视频

报告可以逐帧导出为适合演示文稿的 MP4。需要先安装 Chromium/Chrome 和 ffmpeg：

```bash
python -m nodefusion.host.cli video \
  --run xv6-cow \
  --fps 24 \
  --width 1600 \
  --height 900
```

`--section all` 可以按报告中出现的子系统分别导出，例如 `vm`、`phys`、`sched`、
`syscall` 和 `trap`。导出的 MP4 旁边会有同名 JSON sidecar，记录帧数、分辨率、
输入 HTML 和证据范围。

## 内核集成

内核相关信息集中在 manifest 中：实体如何从快照枚举、字段如何读取、哪个函数对应
哪种事件、如何构建和启动 QEMU。新增内核先编写 TOML；返回值或提交后语义由
`nftrace` 集成补充。

- [Manifest 编写指南](https://github.com/JosephJoshua/nodefusion/wiki/添加内核支持)
- [Manifest 语法参考](https://github.com/JosephJoshua/nodefusion/wiki/Manifest-语法参考)
- [`docs/manifests/AUTHORING.md`](docs/manifests/AUTHORING.md)
- [`docs/manifests/REFERENCE.md`](docs/manifests/REFERENCE.md)
- [`nodefusion/integrations/`](nodefusion/integrations/)
- [`nodefusion/spec/event-stream.md`](nodefusion/spec/event-stream.md)

集成补丁针对文档中指定的上游提交验证。具体补丁和应用命令见
[`nodefusion/integrations/README.md`](nodefusion/integrations/README.md)。补丁扩展
观测边界，QEMU 插件负责基础记录；报告范围由外部观测能够证明的语义决定。

## 代码结构

```text
nodefusion/
├── host/          录制、分析、渲染、审计、视频导出
├── model/         manifest、DWARF、source plan、事件和状态模型
├── manifests/     每个内核一份 TOML 描述
├── plugin/        QEMU TCG plugin（C）
├── integrations/  内核侧 nftrace 补丁和探针
├── spec/          事件流与轨迹格式规范
└── tests/         单元、集成、模糊和语料测试

artifacts/         可提交的 HTML、MP4、JSON sidecar 和覆盖索引
docs/              内核章节说明和 manifest 文档
scripts/           环境检查与 WSL 准备脚本
```

前端只消费统一的时间轴、事件、状态和指标数据。内核差异由 manifest、host 侧
reader/source 和可选的 nftrace 事件表达。

## 测试

普通测试：

```bash
python -m pytest nodefusion/tests -q
```

语料测试在普通命令中默认跳过，以控制运行时间。容量充足时显式运行全部语料：

```bash
NF_CORPUS_MAX_TRACE_MIB=0 \
  python -m pytest nodefusion/tests -q --run-corpus
```

部分测试依赖目标内核源码、带 DWARF 的 ELF、QEMU 或真实 `trace.nfb`；这些输入
缺席时测试显示为 skip。

## 许可

本项目使用 MIT 许可证，见 [`LICENSE`](LICENSE)。xv6-riscv 保留其原作者的版权声明。
