# 添加内核支持

NodeFusion 通过两条通道观察内核。QEMU 插件在函数入口记录事件和参数寄存器，并按一定间隔保存内存快照；内核中的 `nftrace` 探针补充函数入口无法表达的结果值、提交时刻和调度决定。manifest 把目标内核的 ELF/DWARF、内存结构和这两条通道接到统一的数据模型上。

每个内核在 `nodefusion/manifests/` 下有一份 TOML 文件。支持同一内核的多个教学章节或编译 feature 时，仍然使用一份 manifest，通过 DWARF 条件选择各自的数据结构和事件映射。

下面以 `mykernel` 为例。完整字段表见[《Manifest 语法参考》](REFERENCE.md)。已有的 `xv6.toml`、`rcore.toml`、`starry.toml` 和 `ucore.toml` 可以作为实际样例。

## 准备内核构建

先选定一份能够重复构建的源码。记录仓库地址、提交号、构建命令和工具链版本。若一个内核需要覆盖多个章节或配置，每一种形态都要保留一份可供验证的 ELF。

```bash
git -C /path/to/kernel rev-parse HEAD
rustc --version
qemu-system-riscv64 --version
```

编译时保留 DWARF 调试信息。Rust release 构建可以使用：

```bash
CARGO_PROFILE_RELEASE_DEBUG=2 make build
```

C/C++ 工程通常在编译参数中加入 `-g`。最终交给 NodeFusion 的文件应当是未经 strip 的 ELF。QEMU 启动时使用的扁平镜像可以是另一份文件。

检查 ELF 的架构、调试段和符号表：

```bash
file /path/to/kernel.elf
readelf -h /path/to/kernel.elf
readelf -S /path/to/kernel.elf | rg 'debug_info|debug_line|symtab'
shasum -a 256 /path/to/kernel.elf
```

`debug_info` 提供类型和字段，`debug_line` 提供源码位置，`symtab` 提供静态量和函数地址。少掉其中一项时，相关规则会在 probe 或观察点选择阶段报告原因。

接着从源码中找出内核对象的保存位置和主要入口：

```bash
rg -n 'struct (Proc|Process|Thread|Task)|enum .*State' /path/to/kernel
rg -n 'fn (fork|clone|spawn|exit|schedule)|void (fork|exit|scheduler)' /path/to/kernel
rg -n 'PageTable|MemorySet|frame_alloc|kalloc|journal|commit' /path/to/kernel
```

源码用于确认语义，ELF 用于确认本次构建中实际存在的名字和布局。后面的每个类型、字段和函数名都应当能追溯到这份源码与 ELF。

## 建立覆盖清单

先列出需要支持的构建形态和测试程序。例如一个八章教学内核可以写成：

| 构建 | 主要结构 | 测试程序 | 预期通道 |
| --- | --- | --- | --- |
| ch1 | 无进程结构 | 内核启动 | 控制台、函数事件 |
| ch3 | 固定任务数组 | 多任务示例 | 任务快照、调度事件 |
| ch5 | 进程与线程 | fork/exec/wait | 进程关系、生命周期事件 |
| ch6 | 文件系统 | 文件读写 | inode、块缓存、磁盘事件 |
| ch8 | 同步与线程 | 同步测试 | 线程、锁与调度事件 |

同一形态在多种架构上构建时，每个架构单列。SMP、文件系统、网络等 feature 会改变结构或事件语义时，也各占一行。后续验证按这张表逐项进行。

## 写入内核身份

在 `nodefusion/manifests/` 中新建 `mykernel.toml`：

```toml
[kernel]
name = "mykernel"
family = "mykernel"
arches = ["riscv64"]
detect = { any_type = ["mykernel::task::Task"], any_symbol = ["INIT_TASK"] }
```

`name` 是 manifest 的唯一名称，也是 `--kernel-kind mykernel` 的取值。`family` 表示内核家族。`arches` 使用 NodeFusion 的 ELF 架构名。

这里的 `detect` 用于读取 ELF 后识别内核。表中的各组条件同时成立时才算命中；每组数组内部按该组的规则判断。上例要求 `Task` 类型和 `INIT_TASK` 静态量都存在。

目录级自动识别由 `[profile].detect_files` 完成。两处检测发生在不同阶段：录制命令先根据源码目录选择 profile，分析阶段再根据 ELF/DWARF 选择 manifest。两处都要验证。

检测条件宜选用长期存在、足以区分内核的核心类型或静态量。Rust 类型使用完整模块路径。派生内核可能同时命中底层 manifest，可以声明继承关系：

```toml
[kernel]
name = "mykernel"
family = "basekernel"
builds_on = "basekernel"
arches = ["riscv64"]
detect = { any_type = ["mykernel::task::Process"] }
```

当 `mykernel` 和 `basekernel` 同时命中时，检测器让 `mykernel` 生效。两份 manifest 各自保存完整配置。

新增文件后先运行解析和检测相关测试：

```bash
python -m pytest \
  nodefusion/tests/test_manifest_lint.py \
  nodefusion/tests/test_manifest_vocabulary.py \
  nodefusion/tests/test_profile_from_manifest.py -q
```

还要拿每一份目标 ELF 运行一次检测，确认只命中预期的 manifest。可在 Python 中直接查看检测轨迹：

```bash
python - <<'PY'
from nodefusion.model.dwarfsrc import DwarfSource
from nodefusion.model.manifest import load_dir
from nodefusion.model.probe import detect

dw = DwarfSource('/path/to/kernel.elf')
kind, trace = detect(load_dir(), dw)
print('result:', kind)
print(*trace, sep='\n')
PY
```

## 描述实体

实体是内存快照中可以枚举的内核对象，例如进程、线程、缓冲块、打开文件和 inode。每个实体先声明名称、DWARF 类型和语义角色：

```toml
[[entity]]
name = "process"
role = "process"
type = "mykernel::task::Process"
label = "进程"
```

`name` 在本份 manifest 内唯一。`type` 对应 DWARF 类型。`role = "process"` 让进程视图和调度归属能够找到这种实体。

### 找到枚举根

实体需要一条从静态量走到对象集合的路径。假设 `INIT_PROCESS` 保存初始进程，每个进程的 `children` 字段保存子进程，可以写成：

```toml
[[entity.source]]
kind = "tree"
completeness = "reachable_only"
reason = "从初始进程沿 children 枚举；脱离该树的临时对象不会出现。"
steps = [
  { static = "mykernel::task::INIT_PROCESS" },
  { unwrap = ["Lazy", "Arc"] },
  { walk = { children = "inner.children", via = ["SpinLock", "Vec", "Arc"] } },
]
```

执行过程从 `INIT_PROCESS` 的地址开始，解开 `Lazy` 和 `Arc`，再对每个进程读取 `inner.children`。`Vec` 的字段偏移、元素大小以及 `Arc` 的数据偏移从 DWARF 取得。

`completeness` 说明这条来源能覆盖哪些对象。固定全局表通常为 `total`；树遍历为 `reachable_only`；就绪队列为 `ready_only`；合并若干仍不完备的来源时使用 `partial`。取值会进入报告和覆盖率结果。

固定数组的写法较短：

```toml
[[entity.source]]
kind = "table"
completeness = "total"
steps = [
  { static = "PROCESS_POOL" },
  { iter = "array" },
]
```

静态量外面带锁或 cell 时，按照内存中的层次写出 `unwrap`：

```toml
[[entity.source]]
kind = "registry"
completeness = "total"
steps = [
  { static = "TASK_MANAGER" },
  { unwrap = ["Lazy", "SpinLock"] },
  { field = "tasks" },
  { iter = "vec", via = ["Vec", "Option", "Arc"] },
]
```

`via` 从容器层开始写到元素层。上例最终生成 `vec<option<arc>>` reader，空的 `Option` 槽会被略过。

同一内核家族可能在不同章节采用不同结构。把具体条件放在前面，通用来源放在后面：

```toml
[[entity.source]]
kind = "tree"
completeness = "reachable_only"
when = { field_exists = { type = "mykernel::task::Process", field = "children" } }
steps = [
  { static = "INIT_PROCESS" },
  { unwrap = ["Lazy", "Arc"] },
  { walk = { children = "children", via = ["SpinLock", "Vec", "Arc"] } },
]

[[entity.source]]
kind = "table"
completeness = "total"
steps = [
  { static = "PROCESS_POOL" },
  { iter = "array" },
]
```

默认的 `source_combine = "first"` 选择第一条条件成立的来源。就绪队列、当前任务和退出队列需要一起枚举时，在 `[[entity]]` 中加入：

```toml
source_combine = "union"
```

所有成立的来源会依次执行，对象按地址去重。每条来源仍需填写自己的 `completeness` 和 `reason`。

某个章节尚未出现这种实体时，可以使用受条件保护的空来源：

```toml
[[entity.source]]
kind = "batch"
completeness = "none"
when = { type_exists = "mykernel::console::Console" }
reason = "该章节只运行单个内核入口，尚未引入任务结构。"
steps = []
```

空 `steps` 只允许用于 `kind = "batch"` 且 `completeness = "none"` 的来源。

### 读取字段

字段路径相对于实体的 `type`。进程号、状态和调度上下文可以写成：

```toml
[entity.fields]
pid = { path = "pid", reader = "newtype<usize>", role = "id" }
state = { path = "inner.state", reader = "enum", enum = "TaskState", role = "state" }
context = { path = "inner.context", reader = "struct", role = "sched_context" }
```

`path` 只描述内联字段下潜。跨越 `Arc`、裸指针等地址边界时，由 `reader` 明确解引用方式。`reader` 可以逐层组合，例如：

```toml
[entity.fields]
name = { path = "inner.name", reader = "spinlock<string>", role = "name" }
parent = { path = "inner.parent", reader = "option<weak>", role = "id" }
root = { path = "memory", reader = "arc<mutex<field<root_paddr, usize>>>", role = "address_space_root" }
```

需要在所有目标 ELF 中出现的字段放在 `[entity.fields]`。随章节或 feature 出现的字段放在 `[entity.optional_fields]`：

```toml
[entity.optional_fields]
exit_code = { path = "inner.exit_code", reader = "i32", role = "exit_code", feature = "process" }
```

可选字段在当前 ELF 中不存在时会记录为缺席。必需字段缺失时会记录为无法解码，并阻断严格覆盖率。

实体间的引用放在 relations 中：

```toml
[entity.relations]
parent = { path = "inner.parent", reader = "option<weak>", links_to = "process", inverse = "children" }
```

读取出的地址会在当前快照的实体索引中查找。`links_to` 指向另一种实体的 `name`，`inverse` 在目标实体上建立反向边。目标对象没有被 source 枚举到时，快照会记录 dangling relation。

固定表中的空槽使用 liveness 过滤：

```toml
[entity.liveness]
skip_when = { field = "state", equals = "UNUSED" }
```

用于判定的字段应当已经声明并能够稳定读取。字段无法解码时，对象会保留在结果中。

### 显示资源表

缓冲块、文件和 inode 等实体可以直接生成资源表：

```toml
[entity.table]
show_when_any = ["refcnt", "valid"]
empty = "当前没有被占用或有效的缓冲块。"

[[entity.table.column]]
key = "slot"
label = "槽位"
format = "num"
synthetic = true

[[entity.table.column]]
key = "block_id"
label = "块号"
format = "hex"

[[entity.table.column]]
key = "valid"
label = "有效"
format = "bool"
optional = true
```

普通列的 `key` 引用已经声明的字段或关系。`synthetic = true` 的列使用枚举下标。`show_when_any` 只影响显示的行，实体枚举和覆盖率仍使用完整结果。

## 选择函数观察点

`[[watch]]` 依据 DWARF 函数、源码文件和符号表选择函数入口：

```toml
[[watch]]
subsystem = "task"
match = { module = "mykernel::task", fn = ["fork", "exit", "schedule"] }
args = 3
snapshot = "event"
```

`module` 匹配完整模块及其后代。`file` 匹配 C/C++ 的声明文件路径或路径后缀。`fn` 使用大小写敏感的 shell 通配符，匹配函数短名和已知别名。多个条件写在同一个 `match` 中时全部需要成立。

观察规则按书写顺序处理。一个地址被前面的规则选中或排除后，后面的规则不再接管。函数级规则放在前面，子模块规则随后，宽模块规则放在最后。例如先排除高频自旋函数：

```toml
[[watch]]
subsystem = "sync"
match = { module = "mykernel::sync", fn = ["spin_loop", "cpu_relax"] }
skip = true

[[watch]]
subsystem = "sync"
match = { module = "mykernel::sync" }
args = 2
```

用目标 ELF 检查实际选择结果：

```bash
python -m nodefusion.tools.crosscheck_watchsel \
  /path/to/kernel.elf nodefusion/manifests/mykernel.toml
```

`empty_rules` 表示整条规则没有匹配对象；`no_address` 表示 DWARF 中存在函数信息，当前 ELF 没有可武装的入口地址。优化导致函数只剩内联实例时，可以针对必要规则设置 `inlined = true`，随后复查每个生成地址的语义。

高频入口会增加轨迹体积。先录制一趟不抽样的短 workload，统计各入口的命中次数，再决定 `skip` 或 `throttle`。`throttle = N` 用于 `snapshot = "none"` 的普通观察点，每 N 次命中保留一条事件。相关计数会标为 sampled，依赖这些事件的指标也不会显示为精确值。带 `always` 或 `event` 快照的观察点使用各自的快照策略，不应用这项事件抽样。

## 映射统一事件

`[event]` 把函数映射到 `nodefusion/model/kinds.py` 登记的统一事件：

```toml
[event]
"mykernel::task::fork" = { kind = "proc.fork", args = ["parent", "flags"], resource = "process" }
"mykernel::task::exit" = "proc.exit"
"mykernel::task::schedule" = "sched.enter"
```

事件键使用观察点选择后的函数路径。Rust 函数通常写完整路径，C 函数写符号名。`args` 依次命名入口参数寄存器；RISC-V 插件记录 `a0` 至 `a7`。需要使用第七个参数时，watch 的 `args` 至少为 7。

统一事件表示可跨内核比较的语义。函数名称只能作为线索。映射前应读取实现，确认调用阶段、对象粒度、成功条件和参数含义。例如逐页写 PTE 的函数适合 `pagetable.map`，一次映射整个区域的函数适合 `vm.map`。

同一入口可由参数位区分两种事件时，使用 `classify`：

```toml
[event]
"mykernel::task::clone" = { kind = "proc.fork", args = ["flags"], classify = { arg = "flags", mask = 65536, set = "thread.create" } }
```

`mask` 来自目标内核 ABI。位被设置时产生 `thread.create`，清零时产生默认的 `proc.fork`。需要先确认 `flags` 在函数入口确实位于对应寄存器。

一个函数在不同构建中具有不同含义时，可以根据 DWARF 形态选择映射：

```toml
[event]
"mykernel::task::spawn" = [
  { kind = "thread.create", when = { type_exists = "mykernel::task::Thread" } },
  { kind = "proc.create" },
]
```

候选项按顺序判断，最后一项必须是无条件项。

函数入口看不到返回值，也无法确认函数最终成功。分配结果、提交完成、真实调度切换和 clone 成功后的进程/线程类别适合由 `nftrace` 记录。线协议和类型编号见 [`nodefusion/spec/event-stream.md`](../../nodefusion/spec/event-stream.md)，已有补丁和应用命令见 [`nodefusion/integrations/README.md`](../../nodefusion/integrations/README.md)。

新增 `nftrace` 事件时需要同步完成以下工作：

1. 在内核完成目标操作后写入记录，避开持锁区和分配路径；
2. 在 `event-stream.md` 登记固定的记录类型和字段；
3. 更新插件、解析器和分析器；
4. 处理函数入口产生的重复事件；
5. 添加 wire format、截断输入和真实补丁内容测试；
6. 在补丁针对的源码提交上运行 `git apply --check`；
7. 用能够触发成功、失败和边界路径的 workload 录制验证。

观察补丁应只加入观测逻辑。为了让教学内核在新工具链上构建或修复其功能缺陷的改动，应放在单独补丁中。

## 声明不适用的事件

某项机制在目标内核中不存在时，可以在 `[absent]` 中记录：

```toml
[absent]
"log.commit" = { why = "feature", evidence = "文件系统直接写回缓存块；源码中的 block_cache_sync_all() 只遍历并写回脏块，没有日志、事务或恢复记录。" }
```

`why = "feature"` 表示该内核没有对应机制。证据应给出源码位置、主要调用链和搜索过的概念。

内核具有相关行为，当前可寻址入口无法达到统一事件所需粒度时，使用 `granularity`：

```toml
[absent]
"vm.unmap" = { why = "granularity", evidence = "地址空间销毁入口一次清空全部区域；ELF 中没有逐区域调用的函数，入口参数也不含单个区域的起止地址。" }
```

发现可用入口或加入 `nftrace` 探针后，删除对应 absent 项并补上事件映射。一个事件类别不能同时出现在 `[event]` 和 `[absent]` 中。

## 配置构建和录制

`[profile]` 保存从源码目录构建并启动内核所需的信息：

```toml
[profile]
kernel_elf = "build/{crate}"
kernel_image = "build/{crate}.bin"
build = "make build {mv}"
detect_files = ["Makefile", "Cargo.toml"]
required_tools = ["qemu-system-riscv64", "rustc"]
machine_opts = ["-machine", "virt", "-m", "512M", "-bios", "default", "-kernel", "build/{crate}.bin"]
interactive = true
prompt = ">> "
ready_markers = ["Boot complete"]
done_markers = ["All tests passed"]
panic_markers = ["panicked at", "kernel panic"]
exit_marker = 'exit_code=(?P<code>-?[0-9]+)'
halt_markers = ["Power down"]
protect = ["fs.img"]
```

路径相对于 `--kernel` 指向的源码目录。`{crate}` 从根目录 `Cargo.toml` 的 `[package].name` 读取。`{mv}` 展开为 `--lab-stage` 和 `--make-var` 传入的构建参数；使用这些命令行参数时，`build` 中需要保留 `{mv}`。

录制器在构建前移走旧产物，构建结束后检查 ELF、镜像和必需设备，避免把旧文件当作本次结果。`protect` 与设备文件会在校准运行后恢复。

可选设备使用数组表：

```toml
[[profile.device]]
file = "fs.img"
opts = ["-drive", "file=fs.img,if=none,format=raw,id=x0"]
built_when = { file = "Makefile", contains = "fs.img:" }
```

设备文件存在时才附加 `opts`。`built_when` 用来判断本次构建是否应当生成该文件，构建后的产物检查会使用这个判断。

一个内核家族的后期章节可能增加 shell。可以按源码中的稳定标识切换 profile：

```toml
[profile.shell_probe]
dir = "os/src"
ident = "run_shell"
```

匹配成功后，`interactive` 会设为 true，并使用 `shell_prompt` 和 `shell_ready_marker`。完整的 marker 判定顺序见[profile 参考](REFERENCE.md#profile)。

先运行环境检查，再进行录制：

```bash
python -m nodefusion.host.cli doctor

python -m nodefusion.host.cli record \
  --kernel /path/to/kernel \
  --kernel-kind mykernel \
  --program smoke_test \
  --name mykernel-smoke
```

长时间 workload 可以先限定观察子系统：

```bash
python -m nodefusion.host.cli record \
  --kernel /path/to/kernel \
  --kernel-kind mykernel \
  --program fs_test \
  --watch-subsystem syscall \
  --watch-subsystem inode \
  --name mykernel-fs
```

这类运行只用于验证所选子系统。全覆盖运行仍需武装覆盖清单中适用的全部观察点。

## 验证每一种构建

先运行静态测试：

```bash
python -m pytest \
  nodefusion/tests/test_manifest_lint.py \
  nodefusion/tests/test_manifest_vocabulary.py \
  nodefusion/tests/test_event_kind_registry.py \
  nodefusion/tests/test_event_when_branches.py \
  nodefusion/tests/test_profile_from_manifest.py \
  nodefusion/tests/test_kernel_integrations.py -q
```

用目标 ELF 检查 DWARF 读取和观察点选择：

```bash
python -m nodefusion.tools.crosscheck_dwarf /path/to/kernel.elf
python -m nodefusion.tools.crosscheck_watchsel \
  /path/to/kernel.elf nodefusion/manifests/mykernel.toml
```

`crosscheck_dwarf` 对比两套 DWARF 读取路径。没有共同结构体、字段布局不一致或出现悬空类型引用时，命令会退出非零。

每一行覆盖清单至少录制一趟。测试程序应当主动触发该构建中适用的实体、关系和事件。例如文件系统构建需要覆盖创建、读写、关闭、inode 查找、块缓存和磁盘 I/O；进程构建需要覆盖创建、exec、退出、等待和调度切换。

录制完成后重新渲染，并生成机器可读的覆盖率结果：

```bash
python -m nodefusion.host.cli render \
  --run mykernel-smoke \
  --event-stream never

python -m nodefusion.host.cli audit \
  --run mykernel-smoke \
  --json > /tmp/mykernel-smoke.coverage.json
```

`audit` 退出码为零且 JSON 中 `complete` 为 true，才表示该次运行的所有适用项完整。这个结论只覆盖当前 ELF 和 workload。

再运行报告数据、产物写入和覆盖证据测试：

```bash
python -m pytest \
  nodefusion/tests/test_bundle_shape.py \
  nodefusion/tests/test_artifact_output_safety.py \
  nodefusion/tests/test_coverage_evidence.py -q
```

检查运行目录中的材料：

- `manifest.json` 中的 `kernel_kind`、ELF SHA-256、构建信息和观察点选择与本次运行一致；
- `trace.nfb` 正常收尾，报告中没有 trace incomplete 提示；
- 进程、线程和资源表中的对象数量能够由 workload 解释；
- 必需字段没有 `undecodable`，关系没有意外的 dangling 目标；
- 事件类型、参数、资源和先后顺序与源码路径一致；
- 经过 throttle 的事件和派生指标显示为 sampled；
- absent 项在报告元数据中保留其原因和证据；
- HTML 能够离线打开，各页签和时间线正常渲染。

浏览器检查可以从运行目录启动一个本地服务器：

```bash
python -m http.server 8000 --directory nodefusion/runs/mykernel-smoke
```

打开 `http://127.0.0.1:8000/mykernel-smoke.html`，依次检查概览、进程、资源和事件页面，并查看浏览器控制台。报告应当在断网状态下工作，切换时间点后表格与时间线同步更新。

需要长期保存本次验证时，对覆盖 JSON、ELF、二进制轨迹和 HTML 计算校验和：

```bash
shasum -a 256 \
  /tmp/mykernel-smoke.coverage.json \
  /path/to/kernel.elf \
  nodefusion/runs/mykernel-smoke/trace.nfb \
  nodefusion/runs/mykernel-smoke/mykernel-smoke.html
```

需要导出完整 `events.jsonl` 时使用：

```bash
python -m nodefusion.host.cli render \
  --run mykernel-smoke \
  --event-stream always
```

`auto` 模式会在预计文件超过 256 MiB 或磁盘余量不足时跳过 JSONL。HTML 为交互性能保留抽样事件时，bundle 中会记录原始数、保留数和抽样方法。事件总数和精确指标仍以二进制轨迹及分析结果为准。

本机已有多份运行记录时，可以执行 corpus 测试：

```bash
python -m pytest nodefusion/tests --run-corpus
```

默认只发现不超过 256 MiB 的轨迹。归档机上穷举全部记录使用：

```bash
NF_CORPUS_MAX_TRACE_MIB=0 \
  python -m pytest nodefusion/tests --run-corpus
```

## 完成内核支持

覆盖清单中的每一种构建都应满足以下条件：

- 源码提交、构建命令、工具链和 ELF SHA-256 已记录；
- 目录检测和 ELF 检测均唯一命中；
- 所有适用实体都有能够执行的 source；
- 必需字段和关系能够从该 ELF 解码；
- source 的完整性与内核实际保存的对象集合一致；
- 所有适用子系统都有 workload 和观察点；
- 每个统一事件都经过源码语义核对；
- 函数入口缺少的结果语义由 `nftrace` 提供，或在 absent 中留下可复查证据；
- profile 能够从干净源码目录构建并启动该内核；
- 补丁在指定提交上通过 `git apply --check`；
- 实际录制正常收尾，严格 audit 通过；
- HTML、可选 JSONL 和运行元数据相互一致；
- 保存的覆盖 JSON、ELF、轨迹和 HTML 校验和能够重新核对；
- 普通测试与 corpus 测试通过。

一份 manifest 覆盖多个章节时，逐章保存 audit JSON。一个面向多种 feature 或架构的内核同样逐配置保存。所有行通过后，才能把这份 manifest 视为覆盖了清单中的完整内核家族。

## 排查常见问题

### 找不到类型或字段

先在目标 ELF 上运行 `crosscheck_dwarf`。Rust 泛型类型使用完整路径；短名遇到同名类型时会产生歧义。字段路径只穿过内联包装，跨指针需要 reader 或 source 中的 `unwrap`、`deref`。

### source 编译成功，枚举结果为空

查看 source trace 和运行期 problems。常见原因包括静态根尚未初始化、容器布局未能从 DWARF 解析、裸指针为空、per-CPU 布局尚未安装，以及 liveness 将所有槽位过滤掉。

### watch 规则没有选中函数

查看 `crosscheck_watchsel` 的 `empty_rules` 与 `no_address`。C 文件名按路径后缀匹配；Rust trait 实现会先转换为实现类型路径；`fn` 通配符匹配短名。内联实例需要显式启用 `inlined`。

### 一个入口同时创建进程和线程

入口参数中有稳定 ABI 标志时使用 `classify`。成功结果由函数内部才能确定时加入 `nftrace` 探针，并让分析器消除入口事件的重复计数。

### 报告中的计数标为 sampled

检查命中该事件的 watch 是否设置了 `throttle`，以及派生指标是否依赖该事件。需要精确计数时，缩短 workload 或缩小观察子系统后取消 throttle，重新录制。

### audit 没有达到完整状态

读取 JSON 中的 `blockers`。常见项包括必需指标无数据、字段无法解码、物理页绝对计数缺失、轨迹没有正常收尾，以及某个已声明观察点在本次 workload 中没有产生证据。修复后重新录制；旧轨迹不会获得新加入的观察数据。
