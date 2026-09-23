# NodeFusion 事件流与轨迹格式规范

当前版本：`nodefusion.event-stream/1`、`nodefusion.bundle/1`、轨迹格式
`NFTRACE\x01` v2。魔数末字节 `01` 属于魔数；格式版本位于文件头偏移 8。
写入方生成 v2，读取方兼容 v1 和 v2。

---

## 〇、整体分层

```
   ┌─ 层 1：外部观测（QEMU TCG Plugin，C）
   │    产出：trace.nfb —— 机器记录与可选的 nftrace 记录
   ↓
   ┌─ 层 2：语义重建（Python）
   │    输入：trace.nfb + 内核 ELF 符号表 + 编译期结构体布局
   │    产出：events.jsonl（统一事件流）+ 状态时间线
   ↓
   ┌─ 层 3：数据包（bundle）
   │    产出：给前端消费的紧凑 JSON，zlib+base64 内嵌进 HTML
   ↓
   └─ 层 4：通用可视化（HTML/JS，读取统一模型）
```

层 1 记录机器级事实；层 2 使用 manifest、ELF/DWARF 与可选语义记录解释内核结构；
层 3 压缩报告数据；层 4 读取统一的资源、事件、状态和指标。

---

## 一、设计约束（任何实现都必须遵守）

1. 层 1 运行在 QEMU 进程中，可在 guest 启动失败、panic 或卡死时继续记录。
2. 主时间轴使用全局指令号；tick 和墙钟只作辅助信息。
3. `nftrace` 是可选语义通道。缺少该通道时，其余记录仍可分析。
4. 无法读取或推导的字段使用 unknown 状态，并附带原因。
5. 缓冲区溢出、快照截断、符号缺失和页读取失败写入告警与覆盖结果。

---

## 二、层 1：二进制轨迹格式（trace.nfb）

### 2.1 文件头

| 偏移 | 长度 | 内容 |
| --- | --- | --- |
| 0 | 8 | 魔数 `4E 46 54 52 41 43 45 01`（`"NFTRACE\x01"`） |
| 8 | 4 | 格式版本，小端 u32，当前为 `2` |
| 12 | 4 | 记录头长度，小端 u32，当前为 `16` |

**版本历史**

| 版本 | 变更 |
| --- | --- |
| 1 | 初版 |
| 2 | `DISCON` 负载末尾追加 `mcause / mepc / mtval`；新增 flag 位 5 `NO_MCSR` |

v2 只在 `DISCON` 负载**末尾**追加字段，记录头和其余记录类型都没动，所以：

- 老下游读新轨迹：按 v1 的定长解析，多出来的 24 字节被忽略，结果仍然正确。
- 新下游读老轨迹：按负载实际长度判断这三个字段是否存在。缺失字段报告为
  **不可用**。`0` 在 RISC-V 中表示合法的 cause（指令地址未对齐）。

之后是连续的记录。所有整数**小端**。

### 2.2 记录头（16 字节）

```c
struct nf_rec_hdr {
    uint8_t  type;     // 记录类型
    uint8_t  cpu;      // 产生该记录的 vCPU
    uint16_t len;      // 负载字节数（不含本头）
    uint32_t flags;    // 见 2.3
    uint64_t insn;     // 全局指令号 —— 主时间轴
};
```

未知的 `type` 可以靠 `len` 整条跳过，因此格式向前兼容。

### 2.3 flags

| 位 | 名称 | 含义 |
| --- | --- | --- |
| 0 | `NO_REGS` | 通用寄存器整体读不到，相关字段无效 |
| 1 | `NO_CSR` | S 态 CSR 读不到（scause/sepc/stval/satp/sstatus） |
| 2 | `TRUNCATED` | 因为达到体积上限被截断 |
| 3 | `ZLIB` | 负载中的页内容经 zlib 压缩 |
| 4 | `INCOMPLETE` | 本次快照有物理页读取失败，不完整 |
| 5 | `NO_MCSR` | M 态 CSR 读不到（mcause/mepc/mtval）。v2 起 |

### 2.4 记录类型

| 值 | 名称 | 负载 |
| --- | --- | --- |
| 1 | `META` | UTF-8 文本 `key=value`，记录运行配置 |
| 2 | `SAMPLE` | `pc:u64, satp:u64, sstatus:u64, priv:u32, pad:u32` |
| 3 | `DISCON` | 见下 |
| 4 | `WATCHPC` | 见下 |
| 5 | `SNAPMARK` | `snap_seq:u64, ram_base:u64, page_size:u32, pages_changed:u32, pages_total:u32, pad:u32` |
| 6 | `RAMPAGE` | `page_index:u32, raw_len:u32` + （压缩后的）页内容 |
| 7 | `IDLE` | `kind:u32`（0=进入 idle，1=恢复） |
| 8 | `VCPU` | `up:u32`（1=上线，0=下线） |
| 9 | `WARN` | UTF-8 文本，观测器自身的显式告警 |
| 10 | `END` | `total_insns, snapshots, discons, samples, watch_hits, ram_bytes:u64 ×6, truncated:u32, pad:u32` |
| 11 | `NFTRACE` | 见下。内核侧探针写入的语义记录 |
| 12 | `RETURN` | `pc:u64, target:u64, sp:u64, satp:u64, priv:u32, pad:u32`；开启 `returns=1` 后记录 RISC-V `ret` / `c.jr ra` 执行前的寄存器值 |

**`DISCON`（异常 / 中断 / hostcall）负载**：

```c
uint32_t discon_type;   // 1=中断 2=异常 4=hostcall
uint32_t priv;          // 陷入后所处的特权级：0=U 1=S 3=M
uint64_t from_pc, to_pc;
uint64_t scause, sepc, stval, satp, sstatus;
uint64_t a[8];          // a0..a7，ecall 时 a7 是系统调用号 / SBI EID
uint64_t sp;
/* --- 格式 v2 追加，必须留在末尾 --- */
uint64_t mcause, mepc, mtval;
```

> **RISC-V trap 寄存器选择**
> 每个特权级有独立的 trap 寄存器，陷入目标特权级时只更新对应的一套。
> 陷入 M 态（SBI 调用、M 态时钟中断、固件自己的异常）时，`scause/sepc/stval`
> 保持上一次 S 态 trap 留下的旧值 —— 那个值合法，但跟本次事件毫无关系。
>
> 解释 `DISCON` 时先读取 `priv`：`priv==3` 使用 `mcause/mepc/mtval`，
> 其余情况使用 `scause/sepc/stval`。在 rCore ch4 的一次实测里，一律按 `scause` 解释
> 会得到 2194 次系统调用和 194 次缺页，而真实值是 122 次和 2 次 —— 分别虚高
> 18 倍和 97 倍。

**`WATCHPC`（命中被关注的函数入口）负载**：

```c
uint32_t watch_id;      // watch 列表下标
uint32_t priv;
uint64_t pc, satp;
uint64_t a[8];          // 函数入参（RISC-V 调用约定）
uint64_t sp, ra;
```

**`NFTRACE`（内核主动上报的一条语义）负载**：

```c
uint64_t type;          // 内层记录类型，取值见下表
uint64_t a[4];          // a0..a3，含义由 type 决定
```

该负载固定为五个小端 u64。生产端和读取端共用下表中的类型编号。

内层记录类型（与内核侧 `nftrace.h` 的 `enum` 一一对应）：

| `type` | 名称 | `a0..a3` | 谁发的 |
| --- | --- | --- | --- |
| 1 | `NFT_KALLOC` | `a0` = 分配到的首个物理页地址，0 表示分配失败；`a1` = 请求的页数；`a2/a3` = 操作后的空闲/已分配页数 | 页帧分配器在返回前 |
| 2 | `NFT_PROC_FORK` | `a0` = 父 TID；`a1` = 新进程主线程 TID；`a2..a3` 未用 | clone/clone3 的共同成功路径，且 `CLONE_THREAD` 清零 |
| 3 | `NFT_THREAD_CREATE` | `a0` = 父 TID；`a1` = 新线程 TID；`a2..a3` 未用 | clone/clone3 的共同成功路径，且 `CLONE_THREAD` 置位 |
| 4 | `NFT_SCHED_SWITCH` | `a0/a1` = 切出/切入调度实体 ID；`a2/a3` = 对应的进程或线程 ID，`UINT64_MAX` 表示该调度实体没有此类 ID | 调度器已选定前后任务、进入架构切换之前 |
| 5 | `NFT_KFREE` | `a0` = 释放区间的首个物理页地址；`a1` = 页数；`a2/a3` = 操作后的空闲/已分配页数 | 页帧分配器释放锁后 |
| 6 | `NFT_ALLOCATOR_STATE` | `a0/a1` = 操作后的空闲/已分配页数；`a2..a3` 未用。这是给快照对齐的高频状态样本，不重复列成行为事件 | 可能改变页后端占用、但不是显式页 API 的分配器操作之后 |
| 7 | `NFT_CACHE_READ` | `a0` = 0 未命中、1 命中、2 读取失败；`a1` = 首块编号；`a2` = 请求块数；`a3` = 0 缓存路径、1 直接读取 | 缓存设备完成一次读取请求后；未命中按请求计，不按合并后的设备调用计 |

新增类型时，在本表分配编号，并同步修改内核侧 `nftrace.h`、主机解码器、注册表和测试。
已发布编号保持原有含义，以便继续读取历史轨迹。

2026-09-14 以前归档的三趟录制中，`NFTRACE` 记录数都是 0；对应 watchlist 将
`nftrace_commit_point` 记为 missing。当前 StarryOS、rCore 和 uCoreOS 的
NodeFusion 集成补丁已经提供该生产端，新录制按运行中实际出现的记录声明语义能力。

### 2.5 快照的增量语义

`SNAPMARK` 之后紧跟若干 `RAMPAGE`，它们是**相对上一次快照发生变化的页**。
消费者需要维护一份累积镜像：从全零开始，按顺序打上每次的增量，
任意时刻这份镜像就是那一刻的完整 guest 物理内存。

第一次快照会写出所有非零页。对 xv6 而言这基本是整个 128 MiB —— 因为 `kfree`
会把每个空闲页 `memset` 成 `0x01`。这也是为什么页内容必须压缩：
不压缩一次全量快照就是 128 MiB，压缩后约 1.4 MiB。

### 2.6 快照节奏

参数 `snapstart` 把运行切成两段：之前用 `bootsnap` 间隔（稀疏），之后用 `snap` 间隔（密集）。
xv6 启动能占掉整次运行 95% 以上的指令，均匀撒快照会把分辨率浪费在一个每次都一样的
启动过程上。`snapstart` 由 host 侧的校准跑测出（最后一次 `exec` 的指令号）。

### 2.7 插件参数

```
-plugin libnf.so,out=<路径>[,sample=N][,snap=N][,bootsnap=N][,snapstart=N]
                        [,evsnapmin=N][,evsnapmax=N]
                        [,watch=<文件>][,rambase=N][,ramsize=N][,maxram=N]
                        [,returns=0|1]
```

`evsnapmin` / `evsnapmax` 限流事件触发的快照：两次之间至少隔 `evsnapmin` 条指令，
整次运行最多 `evsnapmax` 张。只管 `@esnap:`，不管 `@snap:`。

`returns=1` 是可选的 RISC-V 返回指令通道。主机端只连接返回地址、栈指针、
地址空间和直接调用方均匹配的已观察函数帧；任务切换与陷入会截断链。
默认关闭，旧轨迹继续显示入口顺序与直接调用方。

`watch` 文件每行 `<十六进制地址> <名字>`，名字上可以带一个前缀：

| 前缀 | 含义 |
| --- | --- |
| 无 | 只记一条 `WATCHPC` |
| `@snap:` | 命中就抓一次完整物理内存快照，**不受限流**。给崩溃现场用（`@snap:panic`） |
| `@esnap:` | 同上，但受 `evsnapmin` / `evsnapmax` 限流。给会反复命中的普通事件用 |
| `@nft:` | nftrace 提交点：命中时读 `a0` 指向的那条 guest 语义记录，写成一条 `NFTRACE`（类型 11）。内核里没有 nftrace 就不配这种点 |

`@snap:` 适合 panic 等单次关键点；`@esnap:` 用于可能高频命中的普通事件。

---

## 三、层 2：统一事件流（events.jsonl）

JSON Lines，UTF-8。第一行是 `meta`，其后每行一个事件。

### 3.1 meta 行

```json
{"type":"meta","schema":"nodefusion.event-stream/1","run":"cow-on",
 "program":"nfcowcompare 256","outcome":"completed",
 "kernel":"...","lab_stage":5,"total_insns":4812345678,
 "icount_shift":3,"cpus":1,"snapshots":110,"plugin_meta":{},"notes":[]}
```

### 3.2 事件行

```json
{"insn":4680123456,"tick":37,"cpu":0,"pid":4,"proc":"nfcowcompare",
 "kind":"trap.page_fault","resource":"vm","pc":4096,"func":"usertrap",
 "detail":{"scause":15,"stval":2415923200,"fault_kind":"store",
           "cause_name":"存数缺页"},
 "unknown":[]}
```

| 字段 | 含义 |
| --- | --- |
| `insn` | 指令号，**主时间轴**，必填 |
| `tick` | 该时刻可用的内核 tick，可能为空 |
| `cpu` | vCPU 号 |
| `pid` / `proc` | 归属进程；由上下文切换重建，未知时省略 |
| `kind` | 事件类型（见 3.3） |
| `resource` | 资源类别（见 3.4） |
| `pc` / `func` | 发生位置与所在函数 |
| `detail` | 随类型解释的参数，来源包括寄存器、函数参数和 `nftrace` 记录 |
| `unknown` | 因缺少 guest 语义而无法确定的字段名列表 |

### 3.3 事件类型

事件注册表位于 `nodefusion/model/kinds.py` 的 `KINDS`。manifest 只能引用已经登记的
类别。下表列出常用前缀；完整集合以注册表为准。

`kinds.py` 还保存词汇审计结果：

| 表 | 意思 |
| --- | --- |
| `UNRESOLVED` | 待核对的疑似同义词及所需证据 |
| `RESOLVED_DISTINCT` | 已确认语义不同的类别 |
| `RESOLVED_MERGED` | 已合并的同义类别 |
| `RESOLVED_TOLERATED` | 暂时并存的同义类别与重新评估条件 |
| `RESOLVED_PENDING_CHANGE` | 已确定方案、等待输出迁移的类别 |
| `RESOLVED_DECLINED` | 经核对后未加入注册表的提议 |
| `UNDECIDABLE_FROM_TRACES` | 当前语料没有足够事件用于判断的类别 |
| `RETIRED` | 历史名称到当前名称的映射 |

录制时的事件类别保存在 `watchlist.json` 中。分析历史轨迹时优先使用该值；`RETIRED`
记录旧名称的对应关系。各组的 `measured` 字段保存源码或运行数据依据。

| 前缀 | 事件（举例，不全） |
| --- | --- |
| `syscall.` | `syscall.enter`（由用户态 ecall 识别，a7=调用号）、`syscall.dispatch` |
| `trap.` | `trap.page_fault`、`trap.exception`、`trap.usertrap`、`trap.kerneltrap`、`trap.userret` |
| `interrupt.` | `interrupt.timer`、`interrupt.external`、`interrupt.software`、`interrupt.clock`、`interrupt.dispatch` |
| `firmware.` | `sbi.call`、`firmware.interrupt`、`firmware.trap` —— 陷入 M 态的事件，发生在**被观察内核之下**的固件层（OpenSBI / RustSBI）。内核自己看不到这一层，观测器能看到 |
| `sched.` | `sched.switch`（上下文切换）、`sched.enter`、`sched.yield` |
| `sync.` | `sync.sleep`、`sync.wakeup` |
| `proc.` | `proc.fork`、`proc.exec`、`proc.exit`、`proc.wait`、`proc.kill`、`proc.alloc`、`proc.free`、`proc.spawn` |
| `phys.` | `phys.alloc`、`phys.free` |
| `vm.` | `vm.copy`、`vm.grow`、`vm.shrink`、`vm.free`、`vm.copyin`、`vm.copyout` |
| `pagetable.` | `pagetable.map`、`pagetable.unmap`、`pagetable.freewalk` |
| `bcache.` | `bcache.get`、`bcache.read`、`bcache.write`、`bcache.release` |
| `log.` | `log.begin`、`log.end`、`log.write`、`log.commit`、`log.install`、`log.recover` |
| `disk.` | `disk.io`、`disk.interrupt`、`disk.balloc`、`disk.bfree` |
| `inode.` | `inode.get`、`inode.alloc`、`inode.put`、`inode.read`、`inode.write`、`inode.bmap`、`inode.namei` … |
| `file.` / `pipe.` | 文件表与管道操作 |
| `kernel.panic` | 内核 panic（同时触发一次崩溃现场快照） |

### 3.4 资源类别

`phys_page`、`vm`、`pagetable`、`proc`、`sched`、`sync`、`syscall`、`trap`、
`interrupt`、`firmware`、`bcache`、`log`、`disk`、`inode`、`file`、`pipe`、
`panic`、`kernel`。

### 3.5 事件来源

| 事件 | 数据来源 |
| --- | --- |
| **先决：选对寄存器组** | `priv==3`（陷入 M 态）看 `mcause/mepc/mtval`，否则看 `scause/sepc/stval`。下面所有"cause"都指这样选出来的那一个 |
| 系统调用 | `priv==1` 且 cause 8（用户态 `ecall`），a7 是调用号，a0–a5 是参数 |
| 缺页 | `priv==1` 且 cause 12/13/15，`stval` 是出错虚拟地址 |
| 中断 | cause 最高位为 1，低位区分时钟(5)/外部(9) |
| SBI 调用 | `priv==3` 且 cause 9（S 态 `ecall` 陷入 M 态）。按 SBI 规范，a7=EID、a6=FID；EID ≤ 0x0F 是 v0.1 遗留扩展（不看 FID），其余是四个 ASCII 字符拼的魔数 |
| 固件自身的异常 | `priv==3` 的其余 cause。典型是启动时 OpenSBI 探测可选 CSR：读一个本机没实现的 CSR → 非法指令 → 它自己的 M 态处理程序接住并记为"不存在"。**这类事件被观察内核完全看不到**，只有从虚拟机外部才观测得到 |
| 上下文切换 | `swtch(&old, &new)` 的第二个参数等于 `&proc[i].context`，用进程表基址与结构体偏移反解出 slot；等于 `&cpu->context` 则是切回调度器 |
| 进程归属 | 由上述上下文切换维护"每个核当前跑哪个 slot" |
| 物理页释放 | 函数参数或 `NFT_KFREE` 提供释放地址和页数 |
| 物理页分配 | `NFT_KALLOC` 提供分配结果；仅有函数入口时 `allocated_pa` 为 unknown |
| 缓存命中率 | `NFT_CACHE_READ` 逐请求记录，或 manifest 声明的一一对应推导；来源未验证时为 unknown |

---

## 四、层 2：状态时间线

每次物理内存快照都会生成一个状态节点。manifest 中的 entity source 枚举对象，reader
按本次 ELF/DWARF 布局读取字段，table 配置决定报告列。

| 资源 | 来源 |
| --- | --- |
| 通用实体表 | manifest 的 `[[entity]]`、source、field、relation 与 table |
| 页表 | manifest 的 address-space role 和架构页表遍历器 |
| 物理页状态 | 页分配语义记录、空闲结构、页表映射和内核镜像区间 |
| legacy xv6 表 | `proc[]`、`bcache`、`ftable`、`itable` 与编译期布局探针 |

必需字段缺失、reader 无法构造、地址越界或快照页缺失时，资源表标为 unavailable 并记录
原因。可选字段缺失时省略对应列。source 的 `completeness` 随状态进入覆盖审计。

---

## 五、层 3：数据包（bundle）

给前端的紧凑 JSON，结构见 `nodefusion/host/bundle.py`。要点：

- 物理页归属使用游程编码 `[[kind, pid, count], ...]`。
- 事件类型、资源、函数名和进程名使用字符串字典。
- 交互事件上限为 150,000。选择器分别为标准化事件和 `func.*` 诊断事件分配预算；
  超出预算时做系统抽样。
- `event_selection` 记录原始数、保留数、逐类丢弃数和策略版本。
- `meta.capability` 记录语义通道、符号、字段、抽样和轨迹完整性。

---

## 六、扩展与新增内核

内核结构、实体来源、字段、观察点、事件映射和录制 profile 写在
`nodefusion/manifests/<kernel>.toml`。新增事件类别时更新 `model/kinds.py`；新增容器编码
时实现 reader；新增遍历方式时实现 source step；提交后语义通过 `nftrace` 类型扩展。

完整流程见[《添加内核支持》](../../docs/manifests/AUTHORING.md)，字段定义见
[Manifest 语法参考](../../docs/manifests/REFERENCE.md)。
