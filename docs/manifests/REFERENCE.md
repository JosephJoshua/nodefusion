# Manifest 语法参考

NodeFusion 从 `nodefusion/manifests/*.toml` 读取内核描述。实际添加过程见[《添加内核支持》](AUTHORING.md)。解析入口在 `nodefusion/model/manifest.py`，source 的编译和执行分别位于 `nodefusion/model/plan.py` 与 `nodefusion/model/exec.py`。

## 文件结构

一份 manifest 可以包含以下部分：

```toml
[kernel]

[[entity]]
[[entity.source]]
[entity.fields]
[entity.optional_fields]
[entity.relations]
[entity.optional_relations]
[entity.liveness]
[entity.table]
[[entity.table.column]]

[[watch]]
[event]
[absent]

[profile]
[[profile.device]]
[profile.shell_probe]

[syscalls]
```

`[kernel]` 必须存在。实体、观察点和录制 profile 可以分阶段加入。没有 `[profile]` 的 manifest 能够用于分析已有轨迹，不能由 `nodefusion record` 启动。

TOML 行内表必须写在同一行。各节会拒绝未知键，并在错误信息中给出相近拼写。

## `[kernel]`

```toml
[kernel]
name = "mykernel"
family = "mykernel"
arches = ["riscv64", "x86_64"]
detect = { any_type = ["mykernel::task::Task"], all_symbol = ["INIT_TASK"] }
builds_on = "basekernel"
derive_feature_absence_from_symbols = true
```

| 键 | 类型 | 缺省值 | 含义 |
| --- | --- | --- | --- |
| `name` | 字符串 | — | manifest 唯一名称；必需 |
| `family` | 字符串 | `""` | 内核家族名称 |
| `arches` | 字符串数组 | `[]` | 支持的 ELF 架构 |
| `detect` | 表 | `{}` | ELF/DWARF 检测条件 |
| `builds_on` | 字符串 | `""` | 当前 manifest 命中时遮住的基础 manifest |
| `derive_feature_absence_from_symbols` | 布尔值 | `false` | 按当前 ELF 中的实现符号推导 build-local feature absence |

当前架构名包括 `riscv64`、`x86_64`、`aarch64` 和 `loongarch64`。`arches` 与 ELF 不符时，probe 产生警告。

`detect` 接受三种条件：

| 键 | 判定 |
| --- | --- |
| `any_type` | 数组中至少一个 DWARF 类型存在 |
| `any_symbol` | 数组中至少一个 DWARF 变量存在 |
| `all_symbol` | 数组中的 DWARF 变量全部存在 |

同一张 `detect` 表中的条件同时成立才会命中。数组必须为非空字符串数组。多个无继承关系的 manifest 同时命中时，检测结果为歧义。

`derive_feature_absence_from_symbols` 适合跨章节或 feature 共用的 manifest。某个已声明事件类别的全部实现符号在当前 ELF 中均不存在时，该构建会把它视为 feature-level N/A。ELF 中存在实现符号而观察点没有选中时，仍然属于覆盖缺口。

## `[[entity]]`

```toml
[[entity]]
name = "process"
type = "mykernel::task::Process"
label = "进程"
role = "process"
source_combine = "first"
```

| 键 | 类型 | 缺省值 | 含义 |
| --- | --- | --- | --- |
| `name` | 字符串 | — | manifest 内唯一的实体名；必需 |
| `type` | 字符串 | — | DWARF 类型名；必需 |
| `label` | 字符串 | `""` | 报告中的显示名称 |
| `role` | 字符串 | `""` | 实体的跨内核角色 |
| `source_combine` | `first` / `union` | `first` | source 选择方式 |
| `source` | 数组表 | `[]` | 枚举来源 |
| `fields` | 表 | `{}` | 必需字段 |
| `optional_fields` | 表 | `{}` | 可选字段 |
| `relations` | 表 | `{}` | 必需关系 |
| `optional_relations` | 表 | `{}` | 可选关系 |
| `liveness` | 表 | — | 固定槽位的存活条件 |
| `table` | 表 | — | 资源表显示配置 |

当前实体角色由消费端识别 `process` 和 `thread`。没有角色的实体仍可枚举并生成资源表。

`source_combine = "first"` 按声明顺序选取第一条 `when` 成立的 source。`union` 执行全部成立的 source，对象按地址去重。合并后的完整性按 source 声明计算：其中有 `total` 时为 `total`；没有 `total` 且含 `partial` 时为 `partial`；其余不同取值组合为 `partial`。

### `[[entity.source]]`

```toml
[[entity.source]]
kind = "tree"
completeness = "reachable_only"
reason = "从初始进程沿 children 枚举。"
when = { type_exists = "mykernel::task::Process" }
steps = [
  { static = "INIT_PROCESS" },
  { unwrap = ["Lazy", "Arc"] },
  { walk = { children = "children", via = ["SpinLock", "Vec", "Arc"] } },
]
```

| 键 | 类型 | 缺省值 | 含义 |
| --- | --- | --- | --- |
| `kind` | 字符串 | `""` | 来源形态说明；空计划判断也会使用它 |
| `completeness` | 字符串 | `unknown` | 枚举范围 |
| `steps` | 表数组 | — | 从根到实体的执行步骤 |
| `when` | 表 | 无条件 | 当前 ELF 的选择条件 |
| `reason` | 字符串 | `""` | 完整性或来源限制的说明 |

`completeness` 的取值如下：

| 值 | 含义 |
| --- | --- |
| `total` | 来源覆盖内核保存的全部此类对象 |
| `partial` | 来源只覆盖一部分对象，范围由 `reason` 说明 |
| `reachable_only` | 来源覆盖某个根可达的对象 |
| `ready_only` | 来源覆盖处于 ready 集合的对象 |
| `none` | 当前内核形态中没有此类对象 |
| `unknown` | 尚未确认来源范围 |

空 `steps` 仅在 `kind = "batch"` 且 `completeness = "none"` 时编译为明确的空计划。其他空 source 会报告编译失败。

### `when`

source 和事件候选共用下列 DWARF 条件：

```toml
type_case = { type_exists = "mykernel::task::Process" }
field_case = { field_exists = { type = "mykernel::task::Process", field = "children" } }
prefix_case = { field_type = { type = "mykernel::task::Manager", field = "tasks", starts_with = "alloc::vec::Vec<" } }
exact_case = { field_type = { type = "mykernel::task::Manager", field = "tasks", equals = "[Task; 16]" } }
```

上面的键名只是为了让示例成为合法 TOML；实际使用时把右侧表写到 `when = ...`。

`type_exists` 查询类型。`field_exists` 先查询类型，再查询其直接字段。`field_type` 读取直接字段的类型名，并使用 `starts_with` 或 `equals` 判断。一个 `when` 只写一种谓词。

## source steps

每个 step 表只能有一个步骤名。可用的附加参数为 `via`、`key`、`children`、`link`、`next`、`terminator` 和 `layout`；各步骤只读取下面列出的参数。

### `static`

```toml
steps = [
  { static = "mykernel::task::TASK_MANAGER" },
]
```

从静态量开始。解析器先查询 DWARF 变量，并结合 ELF 符号解析 `lazy_static` 等只在符号表中出现的名字。找不到符号时 source 编译失败。后续步骤使用该变量的 DWARF 类型。

### `field`

```toml
steps = [
  { static = "BCACHE" },
  { field = "inner.buffers" },
]
```

沿内联字段路径增加偏移。当前类型已知时，偏移在 source 编译阶段解析。编译阶段无法解析的字段会变成运行期动态步骤；执行器没有运行期类型信息，这条路径会报告 unavailable。因此目标 ELF 上的验证需要确认 trace 中没有 `field_dyn`。

### `deref`

```toml
steps = [
  { static = "CURRENT_TASK" },
  { deref = true },
]
```

按目标架构的指针宽度读取地址。空指针产生空结果；越界或明显无效的地址产生问题记录。等号右侧仅作为 TOML 步骤值，执行过程使用当前 DWARF 类型推导 pointee。

### `unwrap`

```toml
steps = [
  { static = "TASK_MANAGER" },
  { unwrap = ["Lazy", "SpinLock"] },
]
```

依次剥开包装层。名称不区分大小写，也可以写完整泛型类型的外层名称。可用包装层为：

- 地址边界：`Arc`、`Weak`、`Ptr`、`NonNull`；
- 内联包装：`UnsafeCell`、`MaybeDangling`、`MaybeUninit`、`UPSafeCell`；
- 锁：`SpinLock`、`BaseSpinLock`、`Mutex`、`SpinRwLock`；
- 延迟初始化：`LazyInit`、`Lazy`、`LazyLock`。

各层的 payload 偏移从 DWARF 取得。`LazyInit` 和 `Lazy` 会检查初始化状态。`Arc` 与 `Weak` 会检查指针对齐和可用性。

### `descend_to`

```toml
steps = [
  { static = "WRAPPED_TASK" },
  { descend_to = "mykernel::task::TaskInner" },
]
```

在当前结构的直接字段中寻找目标类型，并增加该字段偏移。目标类型为短名或完整名均可。没有匹配字段或出现多个匹配字段时，source 编译失败；后一种情况改用 `field` 明确字段名。

### `iter`

数组、`Vec`、`VecDeque`、`BTreeMap` 和 intrusive list 使用 `iter`。

固定数组：

```toml
steps = [
  { static = "PROCESS_POOL" },
  { iter = "array" },
]
```

数组的元素数和元素大小来自 DWARF。展开数量受运行时 `max_items` 限制，超过上限会标记 truncated。

Rust 容器：

```toml
steps = [
  { static = "TASKS" },
  { unwrap = ["Lazy", "SpinLock"] },
  { iter = "vec", via = ["Vec", "Option", "Arc"] },
]
```

`iter` 的值必须与 `via` 中负责展开的容器一致。`via` 从容器层写到元素层；上例生成 `vec<option<arc>>`。`Vec` 与 `VecDeque` 的 buffer、length、capacity 和 head 偏移来自 DWARF。

`BTreeMap` 需要指定键 reader：

```toml
steps = [
  { static = "PROCESS_MAP" },
  { iter = "btreemap", key = "newtype<u32>", via = ["BTreeMap", "Arc"] },
]
```

结果保留 `[key, value]`，遍历轨迹使用 key 标识节点。映射的 root、length、节点 keys、values 和 edges 布局由 DWARF 解析。

intrusive list 需要给出链字段、next 字段和终止约定：

```toml
steps = [
  { static = "READY_QUEUE" },
  { iter = "list", link = "links", next = "next", terminator = "circular_headed" },
]
```

`terminator` 可以是 `null`、`circular`、`circular_headed` 或整数哨兵。`link` 缺省为 `links`，`next` 缺省为 `next`。链表偏移由 DWARF 解析。

### `walk`

```toml
steps = [
  { static = "INIT_PROCESS" },
  { unwrap = ["Lazy", "Arc"] },
  { walk = { children = "inner.children", via = ["SpinLock", "Vec", "Arc"] } },
]
```

`walk` 把当前对象作为根，读取每个对象的 child 容器并进行广度优先遍历。边可以写 `children` 或 `next`。`via` 的组合规则与 `iter` 相同；BTreeMap 边还要写 `key`。遍历按地址去重，回边计入 cycles，达到 `max_items` 时标记 truncated。

边路径和容器布局应当能在编译阶段从 DWARF 取得。边偏移缺失时，执行器保留根对象并记录问题。

### `percpu`

链接脚本提供 per-CPU 区边界时：

```toml
steps = [
  { percpu = "mykernel::run_queue::RUN_QUEUE" },
]
```

默认路径查询 `_percpu_start`、`_percpu_end`、`_percpu_load_start` 和 `_percpu_load_end`，计算模板内偏移、stride 和 CPU 数。未加 `__PERCPU_` 前缀的名字会同时查询同模块下的 `__PERCPU_` 兄弟符号。

运行期安装 per-CPU 布局时：

```toml
steps = [
  { percpu = "mykernel::run_queue::RUN_QUEUE", layout = "mykernel::percpu::INSTALLED_LAYOUT" },
]
```

layout 对象需要能够下潜到 `region.runtime_base`、`region.area_stride`、`region.area_count` 和 `template_base`。这些值在每一帧快照中读取。布局尚未安装时，此帧没有结果并带有原因。

### `index`

```toml
steps = [
  { static = "TASK_POINTERS" },
  { index = 2 },
  { deref = true },
]
```

把当前地址增加 `index * ptr_size`。这一实现适用于指针槽数组。数组元素不是指针宽度时，使用 `iter = "array"`。

### `from`

```toml
steps = [
  { from = "process.threads" },
]
```

当前解析器会接受并建立实体依赖，执行器尚未把已解析关系注入 `from` reader。这一步不能用于新的工作中。需要从父实体枚举子对象时，先用独立静态根、`walk` 或 `source_combine = "union"` 表达；缺少可用表达时再扩展通用执行器。

## 字段和关系

四个字段表使用同一种格式：

```toml
[entity.fields]
pid = { path = "inner.pid", reader = "newtype<usize>", role = "id" }

[entity.optional_fields]
name = { path = "inner.name", reader = "string", role = "name", feature = "task-name" }

[entity.relations]
parent = { path = "inner.parent", reader = "option<weak>", links_to = "process", inverse = "children" }

[entity.optional_relations]
owner = { path = "owner", reader = "option<struct>", links_to = "process" }
```

| 键 | 类型 | 含义 |
| --- | --- | --- |
| `path` | 字符串 | 相对于实体类型的字段路径；必需 |
| `reader` | 字符串 | 内存编码的 reader；省略后字段无法解码 |
| `role` | 字符串 | 跨内核字段角色 |
| `enum` | 字符串 | `reader = "enum"` 使用的枚举类型名 |
| `links_to` | 字符串 | 关系指向的实体名 |
| `inverse` | 字符串 | 在目标实体上建立的反向关系名 |
| `feature` | 字符串 | 可选字段所属的编译 feature |

必需字段不存在时状态为 `undecodable`；可选字段不存在时状态为 `absent`。字段存在而 reader 不能构造或访存失败时，两类字段都会记录无法解码。

`inverse` 依赖 `links_to`。关系 reader 返回单个地址或地址数组；目标地址在本帧没有对应实体时计为 dangling。

字段 role 为闭集：

| role | 用途 |
| --- | --- |
| `id` | pid、tid、VM ID 等对象标识 |
| `name` | 显示名称 |
| `state` | 调度或生命周期状态 |
| `address_space_root` | 页表根物理地址或 satp 值 |
| `priority` | 调度优先级 |
| `exit_code` | 退出码 |
| `trap_context` | 用户态寄存器保存区地址 |
| `sched_context` | 内核态调度上下文地址 |

添加新的跨内核角色时，先更新 `nodefusion/model/roles.py` 及消费端测试。

`verified` 仍是解析器接受的兼容字段，运行时不读取它。验证状态应当由必需/可选字段、测试和覆盖率结果表达。

## readers

reader 名不区分大小写，尖括号表示组合。`spinlock<vec<arc>>` 会先定位锁内数据，再展开 `Vec`，最后把每项作为 `Arc` 读取。布局参数由字段的 DWARF 类型逐层生成。

### 整数、布尔和枚举

| reader | 结果 |
| --- | --- |
| `u8`、`u16`、`u32`、`u64` | 对应宽度的无符号整数 |
| `i8`、`i16`、`i32`、`i64` | 对应宽度的有符号整数 |
| `usize`、`isize` | 按 ELF 指针宽度读取 |
| `ppn` | 读取 `usize` 后左移页大小位数，得到物理地址 |
| `bool` | 读取 Rust bool；只接受 0 和 1 |
| `enum` | 按 DWARF 枚举表把判别值转换为变体名 |
| `atomic<T>` | 按内层 reader 读取原子值 |
| `newtype<T>` | 读取单字段包装的 `__0` |
| `bitfield` | 读取指定 offset 和 width 的位段；manifest 当前无法传入这两个参数 |
| `unit` | 返回空值，常用于只关心 key 的 map |

`enum` 优先使用字段表中的 `enum`，省略时使用字段自身的 DWARF 类型。未知判别值保留为整数。

### 指针和引用计数

| reader | 结果 |
| --- | --- |
| `ptr`、`nonnull` | 读取裸指针；可继续写 `ptr<T>` |
| `arc`、`arc<T>` | 读取 `ArcInner.data` 地址或继续读取 payload |
| `weak`、`weak<T>` | 读取仍存活的 weak payload；悬垂值返回空 |
| `option<arc>` | Rust `Option<Arc<_>>` 的 niche 布局 |
| `option<weak>` | Rust `Option<Weak<_>>` 的 niche 布局 |
| `option<struct>`、`option<ptr>` | 以空指针表示 None 的结构/指针布局 |
| `struct` | 返回当前内嵌结构的地址，不访存 |

`option<T>` 当前只支持表中四种内层。其他 Rust enum 布局使用 `variant` 明确判别值和载荷。

### 内联包装

`unsafecell<T>`、`maybedangling<T>`、`maybeuninit<T>`、`upsafecell<T>`、`spinlock<T>`、`basespinlock<T>`、`mutex<T>` 和 `spinrwlock<T>` 根据 DWARF 中的字段定位 payload。

`lazyinit<T>`、`lazy<T>` 和 `lazylock<T>` 还会读取初始化状态。未初始化、初始化进行中或初始化失败的对象返回 unavailable。

这些 reader 不假定 Rust 字段顺序。目标 DWARF 中找不到所需 payload 字段时，字段无法解码。

### 容器和字符串

| reader | 条件与结果 |
| --- | --- |
| `array<T>` | 元素数和元素大小来自 DWARF |
| `vec<T>` | 展开 Rust `Vec<T>` |
| `vecdeque<T>` | 按 head、length 和 capacity 展开 `VecDeque<T>` |
| `btreemap<K,V>` | 遍历 Rust `BTreeMap`，每项返回 `[key, value]` |
| `string` | 读取 Rust UTF-8 `String`，长度上限 4096 字节 |
| `cstr` | 读取固定数组长度范围内的 NUL 结尾 UTF-8 字符串 |

`cstr` 的 `maxlen` 来自字段的 DWARF 数组上界，适用于 `char name[N]`。指针形式的 C 字符串没有可由 manifest 提供的独立长度参数，当前 reader 无法安全构造。

容器会检查 length/capacity、地址、对齐和 UTF-8。展开数量达到 `ReadCtx.max_items` 时，结果带有 truncated 记录。

### 取字段、变体和类型视图

| reader | 写法 | 用途 |
| --- | --- | --- |
| `field` | `field<root_paddr, usize>` | 从当前结构的指定字段继续读取 |
| `variant` | `variant<Some, field<__0, ptr>>` | 只读取指定枚举变体的载荷 |
| `astype` | `astype<mykernel::Thread, field<owner, arc>>` | 用指定 DWARF 类型解释当前位置 |

这些 reader 可以嵌套。逗号按最外层尖括号解析，因此完整 Rust 类型名和内层 reader 可以同时出现。

当前 reader 注册表共有以下 43 个名称：

```text
arc array astype atomic basespinlock bitfield bool btreemap cstr enum field
i16 i32 i64 i8 isize lazy lazyinit lazylock maybedangling maybeuninit mutex
newtype nonnull option ppn ptr spinlock spinrwlock string struct u16 u32 u64 u8
unit unsafecell upsafecell usize variant vec vecdeque weak
```

## `[entity.liveness]`

```toml
[entity.liveness]
skip_when = { field = "state", equals = "UNUSED" }
```

当前只实现 `skip_when.field` 与 `skip_when.equals`。字段读取成功且值等于目标值时排除该实体。字段缺失、为空或无法解码时保留实体。

## `[entity.table]`

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
key = "valid"
label = "有效"
format = "bool"
optional = true
```

| 键 | 类型 | 缺省值 | 含义 |
| --- | --- | --- | --- |
| `show_when_any` | 字符串数组 | `[]` | 其中至少一项为真或非空时显示该行 |
| `empty` | 字符串 | `""` | 筛选后没有行时的提示 |
| `column` | 数组表 | — | 列定义；至少一列 |

列的字段如下：

| 键 | 类型 | 缺省值 | 含义 |
| --- | --- | --- | --- |
| `key` | 字符串 | — | 字段/关系名，或 synthetic 列名；必需 |
| `label` | 字符串 | `key` | 列标题 |
| `format` | 字符串 | `""` | `bool`、`hex`、`num`、`enum` 或普通字符串 |
| `values` | 字符串数组 | `[]` | `format = "enum"` 时按整数下标映射文本 |
| `optional` | 布尔值 | `false` | 字段不可用时隐藏此列并附说明 |
| `synthetic` | 布尔值 | `false` | 使用实体枚举下标，无需同名字段 |

普通列必须引用已声明字段或关系。必需列无法解码时，整张表标记为 unavailable。`show_when_any` 只筛选前端行；快照仍保存全部实体。

`address_space` 是 `[[entity]]` 中保留的兼容键。加载器当前不构造地址空间配置，运行时也没有消费者。页表根使用字段 role `address_space_root`；新的地址翻译能力需要先扩展通用模型。

## `[[watch]]`

```toml
[[watch]]
subsystem = "task"
match = { module = "mykernel::task", fn = ["fork", "exit", "schedule*"] }
args = 3
throttle = 0
snapshot = "event"
skip = false
inlined = false
```

| 键 | 类型 | 缺省值 | 含义 |
| --- | --- | --- | --- |
| `subsystem` | 字符串 | `""` | 观察点分组和 `--watch-subsystem` 的值 |
| `match` | 表 | — | 函数选择条件；至少一个条件 |
| `args` | 整数 | `2` | 保存的入口参数寄存器数量 |
| `throttle` | 整数 | `0` | 插件侧命中抽样参数 |
| `snapshot` | `none` / `always` / `event` | `none` | 入口是否请求快照 |
| `skip` | 布尔值 | `false` | 匹配并占用地址，不加入观察点 |
| `inlined` | 布尔值 | `false` | 同时选择 DWARF inline site |

`match` 的四个键都接受字符串或字符串数组：

| 条件 | 匹配方式 |
| --- | --- |
| `module` | 路径等于该模块，或以 `module::` 开头 |
| `module_prefix` | 路径以该字符串开头；`subsystem = "*"` 时用前缀后的第一段作为分组 |
| `file` | DWARF 声明文件等于给定路径，或以 `/给定路径` 结尾 |
| `fn` | 对函数短名和别名执行大小写敏感的 shell 通配符匹配 |

同一 `match` 中的条件同时成立才会命中。候选函数来自 DWARF 与 ELF 符号表；同地址的符号会合并别名。Rust trait 实现路径会转换为实现类型路径。

规则按声明顺序执行。匹配到的地址立即加入已处理集合，后续规则不能改变 subsystem、参数数、节流或快照策略。`skip` 同样占用地址，适合放在宽规则之前。

`snapshot = "always"` 在每次命中时请求快照。`event` 请求受限流保护的事件快照；profile 的 `event_snapshot_min_insns` 可以限制两次事件快照之间的最小指令数。`skip = true` 只能与 `snapshot = "none"` 一起使用。

`throttle = N` 只作用于 `snapshot = "none"` 的普通观察点，每 N 次命中写入一条事件。`N <= 1` 表示不抽样。运行元数据记录抽样观察点，覆盖率把相关计数和依赖指标标为 sampled。带 `always` 或 `event` 快照的观察点不会写入 `@rN`，其数值 `throttle` 不生效。

## `[event]`

键为观察点的完整函数路径或选点后生成的唯一短名，值可以是事件类别字符串、事件表或候选表数组。构建 watchlist 时先查完整路径，再查短名：

```toml
[event]
"mykernel::task::exit" = "proc.exit"
"mykernel::task::fork" = { kind = "proc.fork", args = ["parent", "flags"], resource = "process" }
"mykernel::task::spawn" = [
  { kind = "thread.create", when = { type_exists = "mykernel::task::Thread" } },
  { kind = "proc.create" },
]
```

事件表字段如下：

| 键 | 类型 | 缺省值 | 含义 |
| --- | --- | --- | --- |
| `kind` | 字符串 | — | `nodefusion/model/kinds.py` 中登记的事件类别；必需 |
| `args` | 字符串数组 | `[]` | 入口参数寄存器的名称 |
| `resource` | 字符串 | `""` | 事件关联的资源类别 |
| `operation` | `read` / `write` | `""` | `disk.io` 的方向 |
| `when` | 表 | 无条件 | 候选项的 DWARF 条件 |
| `classify` | 表 | — | 按入口参数位掩码改变事件类别 |

没有事件映射的观察点使用 `func.<观察点名称>`。这些事件保留函数调用信息，不参与统一事件指标。

`args` 的位置对应插件保存的入口寄存器。RISC-V 当前最多记录 `a0` 至 `a7`。显式名称也用于 `classify.arg`。DWARF 形参名不会替代这里的 ABI 位置声明。

`resource` 随事件进入分析结果，用于标识 process、inode、pagetable 等关联对象。空值使用该 watch 的 subsystem。它不读取对象地址；需要对象身份时，还要在 `args` 或 `nftrace` 记录中提供相应值。

`operation` 只允许用于 `kind = "disk.io"`。

候选列表按顺序选择第一条 `when` 成立的项。最后一项必须无条件；此前每一项必须带条件。

`classify` 的格式如下：

```toml
[event]
"mykernel::task::clone" = { kind = "proc.fork", args = ["flags"], classify = { arg = "flags", mask = 65536, set = "thread.create" } }
```

`arg` 必须出现在同一事件的显式 `args` 中，且位于前八项。`mask` 为正整数，`set` 为另一个已登记事件类别。命中位掩码时使用 `set`，其余情况使用 `kind`。

事件类别注册表位于 `nodefusion/model/kinds.py`。新增类别需要定义跨内核语义、更新消费端并添加注册表测试。

## `[absent]`

```toml
[absent]
"log.commit" = { why = "feature", evidence = "文件系统直接写回缓存块；源码中没有 journal、transaction、recovery 路径，ELF 中也没有提交入口。" }
```

每个键是已登记事件类别。值接受 `why`、`evidence`，以及可选的 `when`：

| `why` | 含义 |
| --- | --- |
| `feature` | 目标内核没有该机制 |
| `granularity` | 内核有相关行为，当前可寻址入口达不到统一事件粒度 |

`evidence` 去除首尾空白后至少 24 个字符。内容应当能指向源码位置、调用路径、符号检查或实际测量。无条件的 absent 类别不能同时出现在 `[event]` 中。

跨构建的 manifest 可用 `when = { type_missing = "完整 DWARF 类型名" }` 声明某个构建缺少该机制。例如早期章节尚无块缓存：

```toml
[absent]
"bcache.read" = { why = "feature", when = { type_missing = "mykernel::block_cache::BlockCacheManager" }, evidence = "早期构建没有块缓存管理器，文件系统章节才引入该类型及读取路径。" }
```

分析器成功读取本次 ELF 的 DWARF，且找不到指定类型时，这条 absent 才生效。同一类别可在 `[event]` 中为后续构建保留映射。没有可用的 DWARF 时，条件 absent 不会生效。

`[absent]` 描述内核或观测边界。某次 workload 没有触发一个已支持事件时，保留事件映射，并为该事件增加测试 workload。

## `[profile]`

`[profile]` 让录制器从源码目录构建并启动内核。`kernel_elf`、`kernel_image` 和 `build` 必须同时出现。

```toml
[profile]
kernel_elf = "target/riscv64/release/{crate}"
kernel_image = "target/riscv64/release/{crate}.bin"
build = "make build {mv}"
detect_files = ["Makefile", "Cargo.toml"]
required_tools = ["qemu-system-riscv64"]
machine_opts = ["-machine", "virt", "-m", "512M", "-kernel", "target/riscv64/release/{crate}.bin"]
interactive = false
ready_markers = ["Booting applications"]
done_markers = ["All applications completed"]
panic_markers = ["Panicked at"]
unsupported = ["program", "stdin_after"]
build_deviation = "启用 DWARF 和 nodefusion-trace feature。"
protect = ["fs.img"]
stdin_preload = false
stdin_pad = ""
event_snapshot_min_insns = 500
```

### 构建字段

| 键 | 类型 | 缺省值 | 含义 |
| --- | --- | --- | --- |
| `kernel_elf` | 字符串 | — | 带 DWARF 的 ELF 相对路径 |
| `kernel_image` | 字符串 | — | QEMU 加载的镜像相对路径 |
| `build` | 字符串 | — | 在内核目录执行的构建命令 |
| `detect_files` | 字符串数组 | `[]` | 目录级自动识别要求同时存在的文件 |
| `required_tools` | 字符串数组 | `[]` | 录制前环境检查使用的命令 |
| `build_deviation` | 字符串 | `""` | 可观测构建相对上游的构建差异 |
| `protect` | 字符串数组 | `[]` | 构建与校准期间保护、恢复的文件 |

`{crate}` 会在以上路径、构建命令、机器参数、保护路径和设备路径中展开为根 `Cargo.toml` 的 package name。`{mv}` 只在 build 中由 `--lab-stage` 与 `--make-var` 展开。

构建前，录制器暂存旧 ELF、镜像、保护文件和设备文件。构建结束后必须出现新 ELF、镜像以及 `required_after_build` 判定为必需的文件。

### QEMU 与输入字段

| 键 | 类型 | 缺省值 | 含义 |
| --- | --- | --- | --- |
| `machine_opts` | 字符串数组 | `[]` | 追加到 QEMU 命令的机器、固件和镜像参数 |
| `interactive` | 布尔值 | `false` | 使用 guest shell 驱动 |
| `prompt` | 字符串 | `""` | shell 提示符；空值使用内置提示符 |
| `unsupported` | 字符串数组 | `[]` | 此 profile 忽略的 `RunConfig` 选项名 |
| `stdin_preload` | 布尔值 | `false` | 在等待提示符前发送 workload |
| `stdin_pad` | 字符串 | `""` | preload workload 前写入的字符 |
| `event_snapshot_min_insns` | 整数 | `0` | 两次 event snapshot 之间的最小指令数 |

录制器从 `machine_opts` 的 `-m` 解析 guest RAM 大小，并传给插件。支持 `-m 512M` 和 `-m size=512M,...`。解析失败时会产生警告，插件使用自己的默认值。

`unsupported` 中常用 `program` 和 `stdin_after`。无 shell 的教学内核自行顺序运行应用时，录制器会忽略这些命令行选项并写入 warning。

### 控制台 marker

| 键 | 类型 | 缺省值 | 含义 |
| --- | --- | --- | --- |
| `ready_markers` | 字符串数组 | `[]` | headless 模式的启动完成标记 |
| `done_markers` | 字符串数组 | `[]` | workload 完成标记 |
| `panic_markers` | 字符串数组 | `["panic"]` | panic 标记 |
| `exit_marker` | 字符串 | `""` | shell workload 的完成正则 |
| `halt_markers` | 字符串数组 | `[]` | guest 停机标记；空数组时使用 panic markers |

headless 模式先等待任一 ready marker。没有 ready marker 时立即视为已启动。运行阶段先检查 done，再检查 panic；QEMU 提前退出时也按完整控制台先判断 done 与 panic。

shell 模式先等待 prompt 或第一个 panic marker。workload 开始后，结局按 `exit_marker`、done、panic、新 prompt、halt 的顺序判断。`exit_marker` 可以包含 `(?P<code>...)` 捕获退出码。prompt 与 halt 同时出现且没有 exit marker 时，运行记为 completed，并附带 outcome ambiguous 说明。

### shell probe

```toml
[profile]
kernel_elf = "target/{crate}"
kernel_image = "target/{crate}.bin"
build = "make build"
interactive = false
unsupported = ["program", "stdin_after"]
shell_prompt = "$ "
shell_ready_marker = "shell ready"

[profile.shell_probe]
dir = "os/src"
ident = "run_shell"
```

`shell_probe` 必须同时包含 `dir` 和 `ident`。录制器在 `dir` 下递归读取 `*.rs`，任一文件含有 ident 时，把 profile 切换为 interactive，使用 `shell_prompt`，并用单个 `shell_ready_marker` 替换 ready markers。`program` 和 `stdin_after` 会从 unsupported 中移除。

### `device` 设备

```toml
[[profile.device]]
file = "fs.img"
opts = ["-drive", "file=fs.img,if=none,format=raw,id=x0"]
built_when = { file = "Makefile", contains = "fs.img:" }
```

| 键 | 类型 | 缺省值 | 含义 |
| --- | --- | --- | --- |
| `file` | 字符串 | — | 设备文件相对路径；必需 |
| `opts` | 字符串或字符串数组 | `[]` | 文件存在时追加的 QEMU 参数 |
| `built_when` | 表 | — | 构建是否应生成该设备的源码条件 |

`built_when` 必须同时给出 `file` 和 `contains`。录制器读取该文件并查找字符串；命中时设备在构建后必需。文件无法读取时按必需处理。设备无论是否为本构建必需，都会进入保护集合。

## `[syscalls]`

```toml
[syscalls]
files = ["kernel/syscall.h", "include/syscall*.h"]
pattern = '''#define\s+SYS_(?P<name>[A-Za-z0-9_]+)\s+(?P<num>[0-9]+)'''
```

`files` 是相对内核目录的非空 glob 数组。`pattern` 是 Python 正则，必须包含 `(?P<num>...)` 和 `(?P<name>...)` 两个具名组。分析器用它建立系统调用号到名称的映射。

## 当前兼容字段

下列语法由解析器接受，尚未形成可用的端到端能力：

| 位置 | 字段 | 当前状态 |
| --- | --- | --- |
| `[[entity]]` | `address_space` | 加载时丢弃，没有运行时消费者 |
| `[[entity.source]]` | `nested` | 保存到 `SourceSpec`，source 编译器不读取 |
| 字段/关系 | `verified` | 保存到 `FieldSpec`，probe 与覆盖率不读取 |
| reader | `bitfield` | reader 需要 offset 和 width，字段 schema 尚无参数入口 |
| source step | `from` | 建立依赖并编译，执行器没有关系注入 reader |

新 manifest 不使用这些字段。若某个内核确实需要相应能力，应先补齐数据模型、执行路径、错误报告和测试，再更新本页。

## 扩展通用模型

下列改动属于通用引擎扩展：

- 新的内存编码需要 reader；
- 新的枚举方式需要 source step；
- 新的跨内核字段概念需要 role；
- 新的跨内核事件语义需要 event kind；
- 返回值、提交后状态或内核内部决策需要 `nftrace` 记录。

新增 reader 时要覆盖正确布局、缺失 DWARF、越界内存、空值、损坏值和截断。新增 step 时要覆盖计划编译、执行、循环和数量上限。新增事件或 `nftrace` 记录时要覆盖注册表、wire 编解码、截断输入、重复事件处理、覆盖率和 HTML 数据形状。
