# NodeFusion 事件流与轨迹格式规范

> 这份规范是 NodeFusion 最有复用价值的产物。别的学校、别的内核、别的实验，只要按这个
> 格式产出数据，就能直接复用整套状态重建与可视化层，不需要改一行前端代码。
>
> 版本：`nodefusion.event-stream/1`、`nodefusion.bundle/1`、轨迹格式 `NFTRACE\x01` v2
> （魔数末字节仍是 `01`，那是魔数的一部分，不是版本号；版本号在文件头偏移 8。
> 写入方产出 v2，读取方 v1 v2 都认，见 §2.1）

---

## 〇、整体分层

```
   ┌─ 层 1：外部观测（QEMU TCG Plugin，C）
   │    产出：trace.nfb —— 紧凑二进制，只有"机器层面的事实"
   ↓
   ┌─ 层 2：语义重建（Python）
   │    输入：trace.nfb + 内核 ELF 符号表 + 编译期结构体布局
   │    产出：events.jsonl（统一事件流）+ 状态时间线
   ↓
   ┌─ 层 3：数据包（bundle）
   │    产出：给前端消费的紧凑 JSON，zlib+base64 内嵌进 HTML
   ↓
   └─ 层 4：通用可视化（HTML/JS，对具体实验一无所知）
```

**分层的意义在于职责隔离**：层 1 完全不知道 xv6 有哪些数据结构，它只会数指令、读寄存器、
按物理地址搬字节；层 4 完全不知道什么是写时复制或者 Stride 调度，它只认识资源、事件、
状态和指标。所有关于"这个内核长什么样"的知识都集中在层 2，而且是**运行时从被观察内核
自己身上取的**（符号表 + 编译期 offsetof 探针），不是写死的。

---

## 一、设计约束（任何实现都必须遵守）

1. **观测器在被观察系统之外。** 层 1 运行在 QEMU 进程里，不依赖 guest 执行任何代码。
   guest 没启动、崩了、卡死，观测都继续。
2. **主时间轴是指令号。** 不是 tick、不是墙钟。指令号在 `-icount` 下完全确定，
   同一次实验跑一百遍得到同一条时间轴。tick 作为辅助显示。
3. **可选的 guest 语义只能做增强，不能做前提。** 内核里的 nftrace 有就更丰富，
   没有则链路照常工作。
4. **未知必须显式。** 任何读不到、推不出的字段一律标成未知并说明原因，
   下游必须把它显示成未知。**不允许用推测值填充。**
5. **不静默失败。** 缓冲区溢出、快照截断、符号缺失、页读取失败，全部产生显式告警记录，
   并在最终界面上展示。

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
- 新下游读老轨迹：按负载实际长度判断这三个字段在不在，不在就报告为
  **不可用**，而不是填 0 —— `0` 在 RISC-V 里是合法的 cause（指令地址未对齐），
  拿它顶替缺失值会凭空造出一类不存在的异常。

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
| 11 | `NFTRACE` | 见下。guest 自己写的语义记录，只有内核里带 nftrace 时才会出现 —— 按约束 3，它只能做增强，不能做前提 |

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

> **两套 trap 寄存器，别读错组。**
> RISC-V 每个特权级有自己独立的一套 trap 寄存器，**陷入哪一级就只更新哪一套**。
> 陷入 M 态（SBI 调用、M 态时钟中断、固件自己的异常）时，`scause/sepc/stval`
> 保持上一次 S 态 trap 留下的旧值 —— 那个值合法，但跟本次事件毫无关系。
>
> 所以解释一条 `DISCON` 必须**先看 `priv`**：`priv==3` 用 `mcause/mepc/mtval`，
> 否则用 `scause/sepc/stval`。搞错的后果不是"少一点信息"，而是**编出大量
> 看起来完全正常的假事件**：在 rCore ch4 的一次实测里，一律按 `scause` 解释
> 会得到 2194 次系统调用和 194 次缺页，而真实值是 122 次和 2 次 —— 分别虚高
> 18 倍和 97 倍，且没有任何一条记录会显得可疑。

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

> 这一条以前在上表里写的是「UTF-8 文本」，**是错的**。照那句话写出来的生产端
> 会发一段文本，而读端按 `<5Q` 解，解出五个整数、不报错、然后当成语义填进
> 报告。写在这里免得下一个人再踩。

内层记录类型（与内核侧 `nftrace.h` 的 `enum` 一一对应）：

| `type` | 名称 | `a0..a3` | 谁发的 |
| --- | --- | --- | --- |
| 1 | `NFT_KALLOC` | `a0` = 分配到的首个物理页地址，0 表示分配失败；`a1` = 请求的页数；`a2/a3` = 操作后的空闲/已分配页数 | 页帧分配器在返回前 |
| 2 | `NFT_PROC_FORK` | `a0` = 父 TID；`a1` = 新进程主线程 TID；`a2..a3` 未用 | clone/clone3 的共同成功路径，且 `CLONE_THREAD` 清零 |
| 3 | `NFT_THREAD_CREATE` | `a0` = 父 TID；`a1` = 新线程 TID；`a2..a3` 未用 | clone/clone3 的共同成功路径，且 `CLONE_THREAD` 置位 |
| 4 | `NFT_SCHED_SWITCH` | `a0/a1` = 切出/切入调度实体 ID；`a2/a3` = 对应的进程或线程 ID，`UINT64_MAX` 表示该调度实体没有此类 ID | 调度器已选定前后任务、进入架构切换之前 |
| 5 | `NFT_KFREE` | `a0` = 释放区间的首个物理页地址；`a1` = 页数；`a2/a3` = 操作后的空闲/已分配页数 | 页帧分配器释放锁后 |
| 6 | `NFT_ALLOCATOR_STATE` | `a0/a1` = 操作后的空闲/已分配页数；`a2..a3` 未用。这是给快照对齐的高频状态样本，不重复列成行为事件 | 可能改变页后端占用、但不是显式页 API 的分配器操作之后 |

**加新类型的规矩**：编号在这张表里领，别在代码里就地取一个。领完两边都要改 ——
内核侧的 `nftrace.h` 和主机侧读它的地方（目前是 `analyze.NFT_KALLOC`）。编号
一旦发出去过就不再改用途：旧轨迹里那个数字还是老意思，而轨迹是长期资产。

**历史语料要说清楚**：2026-09-14 以前仓库里的三趟录制 nftrace 记录数**都是
0**，包括 xv6 那趟；`nftrace_commit_point` 在它们的 watchlist `missing` 里。
Starry 的 NodeFusion 集成补丁现在提供真实生产端，并由带该补丁的新录制验证。
旧轨迹不会被改写，仍然明确显示语义通道缺席和相关字段未知。

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
```

`evsnapmin` / `evsnapmax` 限流事件触发的快照：两次之间至少隔 `evsnapmin` 条指令，
整次运行最多 `evsnapmax` 张。只管 `@esnap:`，不管 `@snap:`。

`watch` 文件每行 `<十六进制地址> <名字>`，名字上可以带一个前缀：

| 前缀 | 含义 |
| --- | --- |
| 无 | 只记一条 `WATCHPC` |
| `@snap:` | 命中就抓一次完整物理内存快照，**不受限流**。给崩溃现场用（`@snap:panic`） |
| `@esnap:` | 同上，但受 `evsnapmin` / `evsnapmax` 限流。给会反复命中的普通事件用 |
| `@nft:` | nftrace 提交点：命中时读 `a0` 指向的那条 guest 语义记录，写成一条 `NFTRACE`（类型 11）。内核里没有 nftrace 就不配这种点 |

两个前缀分开是必要的：panic 只会发生一次，漏掉就没有第二次机会，所以不能限流；
而 fork 这类点一次运行能命中几千次，不限流会把录制拖垮。

---

## 三、层 2：统一事件流（events.jsonl）

JSON Lines，UTF-8。第一行是 `meta`，其后每行一个事件。

### 3.1 meta 行

```json
{"type":"meta","schema":"nodefusion.event-stream/1","run":"cow-on",
 "program":"nfcowcompare 256","outcome":"completed",
 "kernel":"...","lab_stage":5,"total_insns":4812345678,
 "icount_shift":3,"cpus":1,"snapshots":110,"plugin_meta":{...},"notes":[]}
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
| `tick` | 该时刻的 xv6 tick（来自最近一次快照），可能为空 |
| `cpu` | vCPU 号 |
| `pid` / `proc` | 归属进程；由上下文切换重建，未知时省略 |
| `kind` | 事件类型（见 3.3） |
| `resource` | 资源类别（见 3.4） |
| `pc` / `func` | 发生位置与所在函数 |
| `detail` | 随类型解释的参数，**全部来自真实寄存器或函数入参** |
| `unknown` | 因缺少 guest 语义而无法确定的字段名列表 |

### 3.3 事件类型

**正本在 `nodefusion/model/kinds.py` 的 `KINDS`**，不在这张表里。下面这张是
**举例**，按前缀各挑几个常见的，方便读的人建立印象 —— 它不全，也不打算全。

之所以把正本放在代码里而不是这份规范里（跟 2.4 的 nftrace 编号表反过来）：
nftrace 的编号是跟仓库外的内核补丁共用的线协议，规范必须持有；事件类别只在
本仓库内部用，没有仓库外的生产者，代码持有更不容易漂。manifest 加载时会拿
`KINDS` 拒绝没登记的类别。

类别是**跨内核共用的词汇** —— 各内核在自己 manifest 的 `[event]` 里把自己的
函数映射过来。共用这件事本身没有自动保障，已经出过同义词：同一个编译器符号
`__rust_alloc_error_handler`，rcore 写 `kernel.alloc_error`、arceos 写
`panic.alloc_handler`（2026-09-03 统一成后者，见 kinds.py 的 B 组；这句原先举
的 `handle_alloc_error` 举错了，那是短名相同的两个符号，不是同义词）。

**加新词之前先去 `kinds.py` 看一眼有没有人给同一件事起过名字。** 那儿有八张
表，看疑似同义的那一对落在哪张：

| 表 | 意思 |
| --- | --- |
| `UNRESOLVED` | 还没裁决。每组写着**要什么证据才能定**，没有合并 |
| `RESOLVED_DISTINCT` | 量过了，**确实是两回事**，别再提合并。带测量数据 |
| `RESOLVED_MERGED` | 量过了，是同义词，**已经并成一个了**。每组写明并进了哪个词、哪些词退休了 |
| `RESOLVED_TOLERATED` | 量过了，说的是同一件事，但**决定不改**。必须写明重新开的触发条件 |
| `RESOLVED_PENDING_CHANGE` | 量过了，也定了该怎么改，但改动会动到输出，所以**还没改**。现在是空的 |
| `RESOLVED_DECLINED` | 提议过的新词，量过之后**决定不加**。里面的词故意不在 `KINDS` 里 |
| `UNDECIDABLE_FROM_TRACES` | `UNRESOLVED` 里那些一次都没出现过的词。现有录制裁决不了它们，得去问 manifest 作者或者专门录一趟 |
| `RETIRED` | 改过名或者被并掉的词：老名字 -> 改成谁、为什么 |

`RETIRED` 那张跟别的不是一类，值得单说。**录下来的 `watchlist.json` 里存着
录制当时的 `kind`，而分析时优先用它，不是用现在 manifest 里写的那个。** 所以
改 manifest 只影响以后录的，老录制里留着老名字 —— 语料的词汇会分叉。录下来的
东西不回头改（跟不许重建内核是同一条纪律），所以分叉是正常的，**分叉没人声明**
才是问题。`RETIRED` 就是那份声明，并且有测试逐个 run 读 `watchlist.json` 核对。

裁决用的两种办法，都记在各组的 `measured` 里：读三个内核的源码（比如映射页面
那组，量出 xv6/ArceOS 是区域级、rCore 是单页级），或者读已录的输出（比如时钟
中断那组，`interrupt.timer` 和 `interrupt.clock` 各 419 次且**严格交错** ——
一次中断两个观察点，并掉会数成 838）。

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

### 3.5 语义是怎么在虚拟机外部推出来的

| 事件 | 外部依据 |
| --- | --- |
| **先决：选对寄存器组** | `priv==3`（陷入 M 态）看 `mcause/mepc/mtval`，否则看 `scause/sepc/stval`。下面所有"cause"都指这样选出来的那一个 |
| 系统调用 | `priv==1` 且 cause 8（用户态 `ecall`），a7 是调用号，a0–a5 是参数 |
| 缺页 | `priv==1` 且 cause 12/13/15，`stval` 是出错虚拟地址 |
| 中断 | cause 最高位为 1，低位区分时钟(5)/外部(9) |
| SBI 调用 | `priv==3` 且 cause 9（S 态 `ecall` 陷入 M 态）。按 SBI 规范，a7=EID、a6=FID；EID ≤ 0x0F 是 v0.1 遗留扩展（不看 FID），其余是四个 ASCII 字符拼的魔数 |
| 固件自身的异常 | `priv==3` 的其余 cause。典型是启动时 OpenSBI 探测可选 CSR：读一个本机没实现的 CSR → 非法指令 → 它自己的 M 态处理程序接住并记为"不存在"。**这类事件被观察内核完全看不到**，只有从虚拟机外部才观测得到 |
| 上下文切换 | `swtch(&old, &new)` 的第二个参数等于 `&proc[i].context`，用进程表基址与结构体偏移反解出 slot；等于 `&cpu->context` 则是切回调度器 |
| 进程归属 | 由上述上下文切换维护"每个核当前跑哪个 slot" |
| 物理页释放 | `kfree(pa)` 的入参就是被释放的页，精确 |
| 物理页分配 | **未知**：`kalloc()` 的返回值在函数入口看不到。标为 `unknown:["allocated_pa"]` |
| 缓存命中率 | 外部推导：`命中 ≈ bread 次数 − 磁盘 I/O 次数`，界面上注明推导方式 |

---

## 四、层 2：状态时间线

每一次物理内存快照都会解出一个完整的 `SystemState`：

| 资源 | 来源 |
| --- | --- |
| 进程表 | 优先走 manifest（`docs/manifests/*.toml` 声明符号、路径、reader，偏移从 DWARF 解），manifest 用不上时退回 `proc[]` 符号地址 + 编译期 offsetof。退回时会在 `notes` 里写明为什么 —— 静默退回等于把"没按预期解"藏起来 |
| 每核当前进程 | `cpus[]` |
| 虚拟内存与页表 | 从 `proc.pagetable` 走 Sv39 三级页表，取全部叶子映射与权限位（含 `PTE_COW`） |
| 物理页归属 | 空闲链表 + 各进程页表 + 内核镜像区间，逐页标注类别与归属 pid |
| COW 引用计数 | `ref` 数组（下标口径由符号大小自动判定） |
| 缓冲区缓存 / 打开文件表 / inode 缓存 | `bcache` / `ftable` / `itable` |
| tick | `ticks` |

**一致性校验**：`kmem`、`ref`、`bcache`、`ftable`、`itable` 在 xv6 里都是匿名结构体，
编译期探针无法对它们取 offsetof，所以偏移按"锁在前、数组紧随其后"推算，
再用 ELF 里该符号的**实际大小**校验：算出来的布局必须和符号大小严格相等。
对不上就把该资源标成 `available=false` 并给出原因，**不猜、不出假数据**。

---

## 五、层 3：数据包（bundle）

给前端的紧凑 JSON，结构见 `nodefusion/host/bundle.py`。要点：

- 物理页归属用**游程编码** `[[kind, pid, count], ...]`，32768 格无损还原。
- 事件的字符串（类型、资源、函数名、进程名）全部走**字典**，避免重复几万遍。
- 事件总量超过上限时对高频低信息量事件抽稀，但 syscall / trap / 中断 / 上下文切换 /
  进程 / 日志 / 磁盘 / panic **永远保留**，并在 meta 里如实写清丢了多少、丢了哪些类型。
- `meta.capability` 是**观测能力自述**：guest 语义有没有、哪些函数这个内核里不存在、
  哪些结构体字段缺失、轨迹有没有被截断。界面顶部原样展示，
  避免把"我们没观测到"误读成"系统里没发生"。

---

## 六、怎么接入一个新资源

以"给某个新内核对象加可视化"为例，只需要改层 2：

1. 在 `host/layout.py` 的 `_FIELDS` 里加上该结构体的字段（编译期探针会自动取偏移，
   字段不存在会被如实记为 missing）。
2. 在 `host/guest.py` 里加一个解码函数，返回 `ResourceTable`，
   并且**必须做符号大小一致性校验**。
3. 在 `host/watchlist.py` 的 `DEFAULT_WATCH` 里加上相关的内核函数入口。
4. 在**那个内核自己的 manifest**（`nodefusion/manifests/<内核>.toml`）的 `[event]` 里
   给这些函数配上事件类型；要收窄资源类别就再写 `resource`，不写则沿用
   `[[watch]] subsystem` 那条规则给的默认值。参数名默认从 DWARF 读，只有想改可读性
   （`b` -> `buf`）或者 DWARF 里根本没有（汇编写的 `swtch`）才写 `args`。

   **不要改 `host/analyze.py` 的 `FUNC_EVENTS`。**那张表从 2026-09-03 起是
   由 `xv6.toml` 生成的（`_func_events_from_manifest()`），只为解码老 bundle
   而存在 —— 那些 run 录的时候 `watchlist.json` 里还没有 `kind` 这个键。
   往生成出来的表里写东西，下次导入就没了。

前端不需要任何改动：新的事件类型会自动出现在事件表的筛选器里，
新的资源表会自动出现在对应页签。

---

## 七、怎么接上一个新内核

上面那一节是给**同一个内核加一种资源**用的，改的是 host 里的代码。换一个内核不该
这么来 —— 那等于把每个内核的细节写死在工具里，加一个内核就得动一次 host。

内核相关的东西一律写在 `docs/manifests/<内核>.toml` 里，代码不认任何具体内核：

1. **认内核**：`[kernel]` 里的 `detect`，给出这个内核独有的类型或符号：
   `detect = { any_type = ["proc"], any_symbol = ["initproc"] }`。
   认不出来就如实说认不出来，不猜 —— `probe.detect` 会把每条没通过的理由都带回来。
2. **声明实体**：`[[entity]]`（`name` / `type` / `label`），`[[entity.source]]` 说明
   怎么从根符号走到每个对象：
   ```toml
   [[entity.source]]
   kind  = "table"
   steps = [{ static = "proc" }, { iter = "array" }]
   ```
   数组长度也从 DWARF 取，不写在 manifest 里 —— 学生会改 `param.h` 里的 `NPROC`。
   同理，字段偏移一律从 DWARF 解：写死的偏移换个构建就不对，**而且不会报错**。
3. **筛掉空槽**：`[entity.liveness]` 的 `skip_when`。xv6 的空闲槽是留在表里标成
   `UNUSED` 的，不筛的话界面上永远挂着 64 个进程。
4. **标角色**：跨内核通用的概念在 `[entity.fields]` 里用 `role` 标出来
   （`id` / `name` / `state` / `address_space_root` / `priority` / `exit_code`），
   界面靠角色找字段，不靠字段名。同一个概念在三个内核里叫三个名字，正是要用角色的
   原因。只有这个内核才有的概念不标角色，按名字取即可。
5. **这个内核可能没有的字段放 `[entity.optional_fields]`**：解不出来算 `absent`
   （正常，不报红）；`[entity.fields]` 里的必需字段解不出来算 `undecodable`
   （故障，要报出来）。三态的意义全在这个区分上。

**当前进度（2026-08-30）**：`task` 实体走通了 xv6；rCore 的 manifest 写完了，但要
带调试信息的构建才解得开（stock release 里 `Lazy` / `Once` 这些包装类型压根没进
DWARF）。其余资源（物理页、页表、bcache…）还在 §六 那条老路上。
