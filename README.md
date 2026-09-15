# NodeFusion

**外部观测工具：把一个真实内核的运行过程重建成事件流、状态快照和可交互的 HTML。**

基础观测不要求修改被观测内核：QEMU 里挂一个 TCG 插件把执行过程录下来，
在外面重建成"哪一刻、谁在跑、内存长什么样、发生了什么"。需要函数入口无法
提供的返回值或提交后语义时，可以应用可选的 `nftrace` 内核集成；缺少它时工具
仍然工作，并把无法证明的字段明确标成未知。

```
QEMU + TCG 插件 → 统一事件流 → 状态重建 → 时间/事件索引 → 自包含 HTML
```

## 支持哪些内核

内核相关的知识**全部写在 manifest 里**（`nodefusion/manifests/*.toml`）：
符号叫什么、哪个函数对应哪种语义事件、结构体字段在什么偏移。
加一个新内核是写一份 TOML，不动 Python 代码。

| 内核 | manifest | 样例产物 |
|------|----------|---------|
| xv6-riscv | `xv6.toml` | [artifacts/xv6](artifacts/xv6) |
| rCore | `rcore.toml` | [artifacts/rcore](artifacts/rcore) |
| ArceOS | `arceos.toml` | [artifacts/arceos](artifacts/arceos) |
| StarryOS | `starry.toml` | [artifact index](artifacts/starryos)；原始轨迹过大，不进 Git |
| uCoreOS | `ucore.toml` | ch1–ch8 均达 100% 适用项覆盖；见 [章节矩阵](docs/kernels/ucoreos/chapters.md) 和 [artifact index](artifacts/ucoreos) |
| AxVisor | `axvisor.toml` | 暂无 |
| reL4 | `rel4.toml` | 暂无 |
| Alien | `alien.toml` | 暂无 |

有 manifest 不等于录过。AxVisor、reL4 和 Alien 目前仍没有完整测量数据；StarryOS、
rCore ch7 和 uCore ch1–ch8 的严格覆盖录制有独立原始归档与 SHA-256 清单。

## 快速开始

```bash
# 环境自检（QEMU、插件、工具链）
python -m nodefusion.host.cli doctor

# 录一趟：--kernel 指向内核源码树，种类能猜就猜，猜不出用 --kernel-kind 指定
python -m nodefusion.host.cli record --kernel ~/src/xv6-riscv --program cowtest --name cow-on

# 渲染成自包含 HTML
python -m nodefusion.host.cli render --run cow-on -o cow-on.html

# 两趟并排对比
python -m nodefusion.host.cli compare --run cow-off --run cow-on -o compare-cow.html

# 严格覆盖门禁；任何适用指标、语义字段、快照通道或完整性检查失败都退出非零
python -m nodefusion.host.cli audit --run cow-on --json
```

超大运行默认先原子写好 HTML，再自动跳过预计超过 256 MiB 的 `events.jsonl`，避免
重复事件流耗尽磁盘。确实需要 JSONL 时使用 `--event-stream always`；只要报告时可用
`--no-event-stream`。

录制产物落在 `nodefusion/runs/<名字>/`。这个目录和存归档内核 ELF 的
`nodefusion/kernels/` 都不进 git —— 一趟录制只有配上录它时那份二进制才解得开，
两者是同一份本地测量数据的两半，一起留、一起丢。

## 目录

| 路径 | 是什么 |
|------|--------|
| `nodefusion/host/` | 录制、渲染、CLI |
| `nodefusion/model/` | 事件模型、符号解析、状态重建 |
| `nodefusion/manifests/` | **每个内核一份 TOML**，内核细节只住在这里 |
| `nodefusion/plugin/` | QEMU TCG 插件（C） |
| `nodefusion/tests/` | 单元、集成与本地录制语料测试 |
| `artifacts/` | 各内核的浏览器样例、审计证据和交叉内核覆盖索引 |
| `docs/manifests/FINDINGS.md` | 移植各内核时量出来的东西 |
| `scripts/` | `nf-doctor.sh`、`nf-setup-wsl.sh` |

## 测试

```bash
python -m pytest nodefusion/tests -q
```

穷举本地忽略目录录制的测试默认明确 skip，避免新放入一份展示录制就让普通测试耗时
暴涨。在容量充足的归档机上用
`NF_CORPUS_MAX_TRACE_MIB=0 python -m pytest nodefusion/tests -q --run-corpus`
做无上限全语料验证；不设环境变量时即使显式开启，也只发现不超过 256 MiB 的轨迹。

需要 Python 3.11+。有些测试要本机有对应内核的 ELF 或源码，没有就自动跳过 ——
跳过是正常的，不是失败。

## 许可

MIT，见 [LICENSE](LICENSE)。xv6-riscv 的版权归其原作者所有。
