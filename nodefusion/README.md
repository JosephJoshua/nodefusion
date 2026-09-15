# NodeFusion 运行观测与可视化

面向**任意内核**的通用操作系统运行观测工具。不是为写时复制、调度、文件系统这几个
实验写死的动画 —— 换一个程序、换一个内核、换一个实验，一行代码都不用改。

内核相关的知识全部住在 `manifests/*.toml` 里：符号叫什么、哪个函数对应哪种语义事件、
结构体字段在什么偏移。加一个内核是写一份 TOML。已有 xv6-riscv、rCore、ArceOS、
StarryOS、AxVisor、reL4、Alien 七份，另有覆盖 uCore Tutorial ch1–ch8 的通用
uCore manifest。

```
外部观测 → 统一事件流 → 状态重建 → 时间/事件索引 → 通用可视化
```

一条命令，从虚拟机上电记录到程序结束、崩溃或超时，最后产出一个自包含、可交互的 HTML：

```bash
python -m nodefusion.host.cli record --kernel ~/src/xv6-riscv --program cowtest
```

---

## 一、它能回答什么问题

**按时间看。** 拖动时间轴定位到任意一条指令 / 任意一个 tick，看那一刻整个系统的样子：
每个核在跑什么、进程表长什么样、128 MiB 物理内存每一页归谁、每个进程的页表和权限位、
打开了哪些文件、缓冲区缓存里有什么、谁睡在哪个通道上。

**按事件看。** 在事件表里筛选某一次系统调用、陷入、中断、上下文切换、睡眠唤醒、缺页、
kalloc/kfree、页表修改、文件系统或磁盘事件，点进去看它的真实参数、前后系统状态的变化、
以及邻近发生了什么。

下面这段是工具在真实运行里重建出来的惰性分配全过程，全部来自虚拟机外部观测：

```
syscall.enter  sbrk(0x100000, ...)                      ← 程序申请 1 MiB
trap.page_fault  store @ 0x5000                         ← 第一次访问触发缺页
trap.usertrap
phys.alloc       分配一页（返回值外部不可见）              ← 如实标注为未知
pagetable.map    va=0x5000 pa=0x87f32000 权限=0x16       ← 这一页落到了哪
```

**两次运行对比。** 同一个工作负载、同一套观测配置，只换内核实现或算法，
用真实资源随时间的变化解释算法差异。

---

## 二、核心设计：观测器在被观察的系统之外

NodeFusion 的观测主体是一个 **QEMU TCG plugin**，运行在 QEMU 进程里、被观察的 xv6 之外。
它从虚拟机上电的第一条指令开始，持续记录：

- 指令计数（主时间轴，逐指令内联累加，精确）
- PC、特权级、satp 的周期采样
- 每一次异常 / 中断（scause、sepc、stval、satp 以及 a0–a7 全套寄存器）
- 关注函数的入口及其入参
- 整个 128 MiB 物理内存的增量快照（按物理地址直接读，不经过 guest 任何代码）

**所以：xv6 根本没启动成功、学生把内核改崩、系统 panic 或者卡死，这些记录都不会停。**
崩溃和启动失败同样会生成可分析的 HTML，学生能回看崩溃前最后执行的 CPU/PC/函数、
异常、内存状态。`panic` 被命中时会立刻额外抓一次完整物理内存快照做崩溃现场取证。

内核里的 `nftrace` 语义通道是**可选增强**，不是前提。它缺席时链路照常工作，
只是某些信息（例如 `kalloc()` 返回的是哪一页）外部确实看不到 ——
这类信息会被**明确标记为未知并说明原因**，绝不用推测值填充。

插件对 xv6 的数据结构一无所知。所有语义解释都在 host 侧的 Python 里完成，
而且结构体偏移是**录制时用被观察内核自己的头文件现算的**（asm-offsets 探针），
不是写死的 —— 学生往 `struct proc` 里加字段也不会让数据悄悄错位。

---

## 三、快速开始

先体检（QEMU、插件、工具链）：

```bash
python -m nodefusion.host.cli doctor
```

WSL 上的环境准备见 [`../scripts/nf-setup-wsl.sh`](../scripts/nf-setup-wsl.sh)。

录制并渲染。`--kernel` 指向内核源码树，必填 —— 从前它默认指向仓库里那棵 xv6 树，
那是 xv6 独有的特权，别的内核都没有，现在去掉了：

```bash
python -m nodefusion.host.cli record --kernel ~/src/xv6-riscv --program cowtest
python -m nodefusion.host.cli record --kernel ~/src/xv6-riscv \
    --program "nfcowcompare 256" --name cow-on \
    --make-var NF_FORK_COPY_MODE=COW

# 对比两次运行
python -m nodefusion.host.cli compare --run cow-off --run cow-on -o compare-cow.html

python -m nodefusion.host.cli audit --run cow-on --json
```

`render` and `compare` always finish the self-contained HTML first.  Their
`events.jsonl` policy defaults to `--event-stream auto`: ordinary streams are
written, but an estimated stream above 256 MiB or one that would consume the
last 512 MiB of disk is skipped with an explicit message.  Use
`--event-stream always` for a deliberate full interchange export, or
`--no-event-stream` when only the report is needed.  Both HTML and JSONL are
written atomically, so an interrupted or full-disk write cannot replace a good
artifact with a plausible-looking partial file.

也可以直接用 Python 入口（Windows 侧）：

```powershell
python -m nodefusion.host record --program cowtest --name cow
python -m nodefusion.host render --run cow
python -m nodefusion.host compare --run cow-off --run cow-on -o compare.html
```

产物都在 `nodefusion/runs/<运行名>/`：

| 文件 | 内容 |
| --- | --- |
| `trace.nfb` | 插件写的原始二进制轨迹（**原始数据，图可以重画，这个没了就没法追溯**） |
| `events.jsonl` | 可选的完整统一事件流，规范见 `spec/event-stream.md`；超大运行默认不重复导出 |
| `<运行名>.html` | 自包含可交互报告 |
| `manifest.json` | 运行清单：内核、构建参数、快照密度、结局、环境 |
| `kernel_layout.json` | 该内核的结构体布局与常量（编译期探针实测） |
| `watchlist.txt/json` | 被观察的函数入口，以及这个内核里**不存在**的那些 |
| `console.log` | guest 串口原样输出 |

---

## 四、目录结构

```
nodefusion/
├── plugin/nf_plugin.c      外部观测器（QEMU TCG plugin，C）
├── host/                   分析与可视化（Python，只用标准库）
│   ├── nftrace.py          二进制轨迹解码
│   ├── nfelf.py            ELF64 符号表解析
│   ├── layout.py           结构体布局编译期探针
│   ├── guest.py            物理内存 → 操作系统语义（页表遍历、proc[]、bcache…）
│   ├── watchlist.py        关注函数列表（含跨版本别名解析）
│   ├── analyze.py          统一事件流 + 状态重建 + 时间/事件索引
│   ├── bundle.py           前端数据包（游程编码 + 字典 + zlib）
│   ├── render.py           自包含 HTML 生成
│   ├── record.py           录制编排
│   ├── cdp.py              最小 Chrome DevTools 客户端（含手写 WebSocket）
│   ├── video.py            报告 HTML → MP4（逐帧驱动 + ffmpeg 编码）
│   └── assets/             前端 CSS / JS
└── spec/event-stream.md    事件流与轨迹格式规范
```

**前端对具体实验一无所知**：它只认识时间轴、事件、状态快照、指标四样东西。
要接入一个新的内核资源，只改 host 侧四个地方，前端零改动 —— 步骤见规范文档第六节。

---

## 五、导出成 MP4 放进 PPT

### 推荐：`video` 子命令（逐帧导出，确定性）

```bash
python -m nodefusion.host.cli video --run cow-on                    # 单次运行
python -m nodefusion.host.cli video --html compare-cow.html         # 对比报告
python -m nodefusion.host.cli video --run lab3-cowtest --fps 30 \
    --copy-to /path/to/ppt/public
```

产出 `<运行名>.mp4`：**H.264 + yuv420p**，PowerPoint「插入 → 视频 → 此设备」直接能用。

这不是屏幕录制，而是**逐帧驱动 + 离屏截图**：无头 Chrome 打开报告后，
每一帧先由导出器把状态摆好（切页签 / 定位时间 / 跳到某个事件）、等这一帧画完再截图，
最后交给 ffmpeg 编码。好处是：

- **确定性** —— 同一份运行记录导出多少次都是同一段视频，不掉帧、没有鼠标乱入；
- 分辨率和帧率随便挑（`--width/--height/--fps`），不受屏幕限制；
- 数据改了重导一遍就行，不用重新录。

**分镜是从数据里现算的，不是写死的**：哪些页签有内容、哪些事件类型这次运行里
真的出现过（`proc.fork` / `vm.copy` / `trap.page_fault` / `sched.switch` …），
都由 `video.py` 读 `nfExport.info()` 决定。换个程序、换个内核，同一套代码照样
生成一段讲得通的视频；内核 panic 的运行会自动多出一段「控制台」镜头。

依赖：一个 Chromium 内核浏览器（自动找 Chrome / Edge / playwright 缓存，
也可用 `NF_CHROME` 指定）+ ffmpeg（Windows PATH 上的，或 WSL 里的）。
CDP 客户端是自己写的，**没有引入任何第三方 Python 包**。

### 备选：URL 参数 + 人肉录屏

HTML 也支持用 URL 参数驱动自动播放，这样录屏不需要人工点按钮：

| 参数 | 作用 |
| --- | --- |
| `?autoplay=1` | 打开即开始播放 |
| `?speed=400` | 每帧停留毫秒数（默认 260） |
| `?loop=1` | 播完循环 |
| `?tab=phys` | 打开时停在指定页签（`phys` / `procs` / `vm` / `events` / `compare` …） |

例如物理内存演化的循环慢放：

```
cow-on.html?tab=phys&autoplay=1&speed=450&loop=1
```

**推荐做法（直接落进 PPT，不需要装任何东西）**：
PowerPoint 的「插入 → 屏幕录制」框选浏览器窗口录一段，停止后视频直接嵌在幻灯片里，
右键还能「将媒体另存为」导出 MP4。

其他方式：Windows 自带 Xbox Game Bar（`Win + Alt + R`）录制后得到 MP4；
或者用 OBS 录制窗口。浏览器建议按 `F11` 全屏并把缩放调到 100%，画面更干净。

建议每段 25–40 秒，一次只讲一件事：
物理内存演化用 `?tab=phys`，算法对比用 `?tab=compare`，
事件因果链用 `?tab=events` 并先筛好事件类型。

---

## 六、已知限制（如实记录）

- **函数入口看不到返回值**。未接入可选 `nftrace` 的内核会把 `kalloc()` 返回物理页
  等字段标为未知；已提供的 StarryOS、rCore 与 uCore 集成会在操作成功后上报精确结果与
  分配器计数。host 不按内核名字分支，只按通道中实际存在的记录解码。
- **快照是有间隔的**。两次快照之间发生并结束的短暂变化不会出现在状态时间线上
  （事件流不受影响，它是指令级的）。间隔写在报告的观测能力说明里。
- **被 SIGTERM 强杀时**可能拿不到最后一次快照；正常结束和 panic 路径都有。
- **缓存命中率是外部推导量**（`bread 次数 − 磁盘 I/O 次数`），界面上已注明推导方式。
- **事件总量超过上限时只抽稀 `func.*` 诊断命中**。所有标准化语义事件（包括
  syscall / trap / 中断 / 调度 / 进程 / 物理内存 / 文件系统 / 磁盘 / panic）
  无损保留；原始数、保留数以及逐 kind 丢弃数都写进报告。
- 默认 watch 列表不含 `walk` / `walkaddr`：一次启动就命中五万次，占掉大半轨迹体积却
  几乎不增加信息量。需要时用 `--watch-all`。
- **导出 MP4 的速度取决于报告大小**：每帧都要在浏览器里重画一次，15 MB 的
  `lab3-cowtest` 大约 1 帧/秒（一段 45 秒的片子要十几分钟），小报告快得多。
  这是拿时间换确定性，导出期间机器可以继续干别的。

穷举本机 `runs/` 的测试默认明确 skip，避免一个新展示轨迹让普通测试耗时突然增长。
在归档机上使用
`NF_CORPUS_MAX_TRACE_MIB=0 python -m pytest nodefusion/tests --run-corpus`
启用无上限全语料验证。
