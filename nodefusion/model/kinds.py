
from __future__ import annotations

GENERATED_PREFIXES: tuple[str, ...] = ("func.",)

KINDS: frozenset[str] = frozenset({
    "bcache.get", "bcache.init", "bcache.read", "bcache.release",
    "bcache.result", "bcache.write",
    "disk.balloc", "disk.bfree", "disk.interrupt", "disk.io",
    "file.alloc", "file.close", "file.dup", "file.read", "file.write",
    "firmware.interrupt", "firmware.trap",
    "heap.add_memory", "heap.alloc", "heap.alloc_zeroed", "heap.free",
    "heap.init", "heap.realloc",
    # inode
    "inode.alloc", "inode.bmap", "inode.dirlookup", "inode.get", "inode.lock",
    "inode.namei", "inode.put", "inode.read", "inode.unlock", "inode.update",
    "inode.write",
    "interrupt.clock", "interrupt.dispatch", "interrupt.external",
    "interrupt.other", "interrupt.software", "interrupt.timer",
    "kernel.alloc_error", "kernel.panic",
    "log.begin", "log.commit", "log.end", "log.install", "log.recover",
    "log.write", "log.write_blocks",
    "pagetable.freewalk", "pagetable.map", "pagetable.new", "pagetable.unmap",
    "panic.alloc", "panic.alloc_handler",
    "phys.alloc", "phys.free",
    "pipe.alloc", "pipe.close", "pipe.read", "pipe.write",
    "proc.alloc", "proc.create", "proc.exec", "proc.exit", "proc.fork",
    "proc.free", "proc.initproc", "proc.kill", "proc.spawn", "proc.wait",
    "sbi.call",
    "sched.enter", "sched.switch", "sched.yield",
    "sched.yield_to_scheduler",
    "signal.raise",
    "sync.sleep", "sync.wakeup",
    "thread.alloc_res", "thread.create", "thread.exit", "thread.free_res",
    "syscall.close", "syscall.condvar_create", "syscall.condvar_signal",
    "syscall.condvar_wait", "syscall.dispatch", "syscall.dup",
    "syscall.enable_deadlock_detect", "syscall.enter", "syscall.exec",
    "syscall.exit", "syscall.fork", "syscall.fstat", "syscall.get_time",
    "syscall.getpid", "syscall.gettid", "syscall.kill", "syscall.linkat",
    "syscall.mmap", "syscall.munmap", "syscall.mutex_create",
    "syscall.mutex_lock", "syscall.mutex_unlock", "syscall.open",
    "syscall.pipe", "syscall.read", "syscall.sbrk", "syscall.semaphore_create",
    "syscall.semaphore_down", "syscall.semaphore_up", "syscall.set_priority",
    "syscall.sigaction", "syscall.sigprocmask", "syscall.sigreturn",
    "syscall.sleep", "syscall.spawn", "syscall.thread_create",
    "syscall.trace", "syscall.unlinkat", "syscall.waitpid", "syscall.waittid",
    "syscall.write", "syscall.yield",
    "task.kstack_alloc", "task.kstack_free", "task.pid_free",
    "trap.enter", "trap.exception", "trap.init", "trap.kernel",
    "trap.kerneltrap", "trap.page_fault", "trap.page_fault_handler", "trap.unknown",
    "trap.userret", "trap.usertrap",
    "vm.aspace_create", "vm.copy", "vm.copyin", "vm.copyout", "vm.free",
    "vm.from_elf", "vm.grow", "vm.growproc", "vm.init", "vm.kernel_init",
    "vm.map", "vm.remove_area", "vm.shrink",
    "vm.translate_buffer", "vm.translate_str", "vm.unmap",
})


UNRESOLVED: tuple[dict[str, object], ...] = ()

#:   B  handle_alloc_error            -> __rust_alloc_error_handler
#:      panic.alloc / panic.alloc_handler。

RESOLVED_PENDING_CHANGE: tuple[dict[str, object], ...] = ()

RESOLVED_MERGED: tuple[dict[str, object], ...] = (
    {
        "group": "A 内核 panic 入口（原 UNRESOLVED A 组，2026-09-03 定了）",
        "kinds": ("kernel.panic", "panic.enter"),
        "merged_into": "kernel.panic",
        "retired": ("panic.enter",),
        "why": "同一个 Rust lang item，同一个角色，三个内核两个拼法：\n"
               "    xv6     panic（老 bundle 没 kind，走 FUNC_EVENTS）  -> kernel.panic\n"
               "    rCore   os::lang_items::panic                      -> kernel.panic\n"
               "    ArceOS  axruntime::lang_items::panic               -> panic.enter\n",
        "decided": "**并成 `kernel.panic`。**\n"
                   "原来这条挂着的理由是「得问写 manifest 的人是不是有意单开 "
                   "panic.* 命名空间，量不出来」。意图确实量不出来，但**后果量得"
                   "出来**，而且后果足够定这件事：\n"
                   "  一、`kernel.panic` 有四个消费者，`panic.enter` 一个都没有：\n"
                   "        app.js:321   时间轴上标红的那两个词之一\n"
                   "        app.js:1133  详情里显示 panic 消息\n"
                   "        video.py:44  关键帧（注释原话：崩了的话这是全片最该看的一帧）\n"
                   "        video.py:128 **判定这趟算不算崩了**，决定要不要加控制台镜头\n"
                   "     也就是说 ArceOS 真崩一次，时间轴不标、详情不显示、"
                   "     视频不取那一帧、而且这趟不会被当成崩了。这不是命名口味，"
                   "     是**崩溃处理在 ArceOS 上整个不工作**。\n"
                   "  二、说 arceos 是「有意单开 panic.* 来分阶段」，这个说法没有"
                   "     旁证：arceos.toml 里 `kernel.*` 一个都没用过（grep 计数 0），"
                   "     所以 `panic.` 不是跟 `kernel.` 对比着选的，它就是这一族"
                   "     在 arceos 那份里的落脚处。\n"
                   "  三、并的代价是零：`panic.enter` 全语料 0 次 —— 它挂在 panic\n"
                   "     路径上，出现即意味着内核崩了，而语料里没有崩过的录制。\n"
                   "**重新开的触发条件**：谁要是真想把 panic 分阶段（进入 / 打印 / "
                   "停机），那就按 C 组改名后的写法来 —— 加 `kernel.panic_xxx` "
                   "这种**说得出自己是哪一阶段**的词，而不是把同一件事换个命名空间"
                   "再写一遍。换命名空间不叫分阶段，那是同义词。\n"
                   "注意 `panic.alloc` / `panic.alloc_handler` **没并**，还在 B 组"
                   "手里 —— 那两个是真的粒度问题，不是同义词问题。所以 `panic.*` "
                   "这个命名空间眼下还在，只是里头没有 `panic.enter` 了。",
    },
)

RESOLVED_TOLERATED: tuple[dict[str, object], ...] = (
    {
        "group": "G 建任务（原 UNRESOLVED G 组，2026-09-03 读源码定了）",
        "kinds": ("proc.alloc", "proc.create", "proc.spawn"),
        "measured": (
            ("xv6", "allocproc()  kernel/proc.c:135",
             "扫 proc[NPROC] 找 UNUSED；allocpid()；kalloc 一个 trapframe；"
             "proc_pagetable()；context.ra=forkret。state 留在 USED，"
             "**没装程序映像**，也**还不可运行**（调用者才置 RUNNABLE）",
             "造出一个空壳任务"),
            ("rcore", "TaskControlBlock::new(elf_data)  os/src/task/task.rs:103",
             "MemorySet::from_elf(elf_data) —— **连程序映像一起装了**；"
             "pid_alloc()；kstack_alloc()；task_status = Ready",
             "造任务 + 装映像，直接就绪"),
            ("arceos", "axtask::api::spawn_task(task: TaskInner)  src/api.rs:128",
             "task.into_arc()；select_run_queue(..).add_task(..)。"
             "**入参就是造好的 TaskInner** —— 这个函数一点没造，只是入队",
             "把已造好的任务放进运行队列"),
        ),
        "why": "跟 E 组是同一类错，但更隐蔽：E 是两个内核给同一件事起了**不同"
               "的词**，G 是两个内核拿**同一个词**罩住了生命周期里不同的阶段。"
               "登记表查不出来 —— arceos 和 rcore 的 proc.create 都拼写正确。\n"
               "三个内核合起来暴露出三个阶段：①造任务对象 ②装程序映像 "
               "③置为可运行/入队。xv6 把①和②分开（allocproc 之后另有 "
               "exec/userinit），rcore 把①②并成一次 new，arceos 只观测到③"
               "（真正的①是 TaskInner::new，没有任何 manifest 映射它）。\n"
               "**顺带更正这一组自己原来的说法**：原 needs 里写「allocproc 是"
               "分配一个 proc 结构……之后还要建页表、装 trapframe」，读了源码"
               "才知道是错的 —— 页表和 trapframe 就在 allocproc 里建。"
               "allocproc 缺的是**程序映像**，不是页表。",
        "at_entry": (
            ("xv6",    "allocproc 入口",   "任务还没造出来 —— 正要进构造流程"),
            ("rcore",  "new(elf) 入口",    "任务还没造出来 —— 正要进构造函数"),
            ("arceos", "spawn_task 入口",  "任务**已经造好了**（它就是入参），"
                                           "但还没进运行队列"),
        ),
        "consequence": "**先纠正上面一段自己的话。** 「arceos 只是入队、没造"
                       "任务」说的是函数，可事件打在入口 —— 那一刻 add_task "
                       "还没执行，任务却已经存在了。所以真实情况不是"
                       "「造」对「入队」，而是**同一件事的两侧**：xv6 和 rCore "
                       "在任务诞生**之前**打点，arceos 在诞生**之后**、可运行"
                       "之前打点。差的是一个相位，不是一个概念。\n"
                       "所以**次数仍然可比** —— 每打一次都对应一个任务诞生，"
                       "一比一。不可比的是**指令号**：arceos 那条 proc.create "
                       "落得偏晚。arceos.toml 自己已经记了这个后果："
                       "「it lands on the spawn entry, before the child is "
                       "queued -- which decodes to `idle` alone and reads "
                       "exactly like a kernel with no tasks」。\n"
                       "还剩一处真的不齐、且跟相位无关：rCore 建任务的时候"
                       "**顺手把程序映像也装了**。\n"
                       "这一条改过两次写法，两次都记在这儿，因为改的过程本身"
                       "是个教训：\n"
                       "  原写法「xv6 要到 exec/userinit 才装」——**错**。读源码"
                       "更正：录这份轨迹的教师版 xv6 里 `uvmfirst` 和 "
                       "`initcode` 一个都不存在（grep 过 "
                       "xv6-riscv_teacher/kernel/*.c），`userinit` 只做 "
                       "allocproc + 置 initproc + cwd + RUNNABLE，一点映像都"
                       "不装。正确说法是 xv6 的映像**只经由 `exec` 进来**。\n"
                       "  第二版写「rCore 的 `new(elf_data)` 把装映像算进来了」"
                       "—— 那是**从别处的源码 checkout 读的签名**，而机器上那份"
                       "checkout 的 `new` 收的是 "
                       "`(process, ustack_base, alloc_user_res)`，压根没有 elf。"
                       "拿错版本的源码解释一份录好的轨迹，正是本仓库栽过的那一"
                       "跤（见 lab3 与教师版 xv6 那条）。\n"
                       "所以最终这一条**不靠任何源码，靠轨迹自己**：rcore.toml "
                       "把 `MemorySet::from_elf` 映射成了 `vm.from_elf`，于是"
                       "「装了几次映像」是可以直接数的。rcore-watchtest 数出来："
                       "\n"
                       "    27229479  proc.create\n"
                       "    27229498  vm.from_elf   ← 入口之后 19 条指令\n"
                       "    28622537  proc.exec\n"
                       "    28622554  vm.from_elf   ← 入口之后 17 条指令\n"
                       "两次装载，一次在 create 体内，一次在 exec 体内 —— "
                       "而 `execs` 只报 1。xv6 那边没有对应的观察点，但源码"
                       "已经保证了「只经由 exec」，所以 lab3 的 3 次 exec "
                       "就是 3 次装载，execs = 3，相等。\n"
                       "眼下这是**潜在**的不是活的：`execs` 只在 metrics JSON "
                       "里，界面一处都没渲染（grep 过 app.js），所以没有任何"
                       "视图把 3 和 1 并排摆出来。",
        "decided": "**容忍这个相位差，不给事件加「入口/出口」维度。**\n"
                   "先撤回 #71 原来提的改法（挪到 sched.* 表示入队）："
                   "入口打点时 add_task 还没执行，改过去一样不准，"
                   "只是换个方向不准。\n"
                   "然后是不加维度的四条理由，全是 2026-09-03 量的：\n"
                   "  一、**次数一比一**，而次数正是所有下游真正在用的东西。"
                   "相位差不影响它。\n"
                   "  二、**没有任何视图跨内核比较单条事件的指令号。**"
                   "`renderCompare` 比的是计数和「某指令号处的状态」，"
                   "表里没有「A 的 proc.create 在 X、B 在 Y」这样一行。"
                   "也就是说那个不可比的量，界面根本没拿出来当可比的用。\n"
                   "  三、唯一把相位写进 manifest 的地方（arceos.toml:412）"
                   "是拿它当**快照节流值的论证**用的，而那个问题已经被那条"
                   "设置本身解决了。不是一个没露出来的缺陷。\n"
                   "  四、看到出口是**录制器**的改动，不是 manifest 的："
                   "插件按入口 PC 触发（`NF_REC_WATCHPC = 命中被关注的函数"
                   "入口`），负载里虽然带了 `ra`，但没有出口观察点这回事。"
                   "而返回值那一类问题内核侧已经有正解 —— `nftrace` 通道，"
                   "内核在 return 前主动上报。**语料里三趟录制的 nftrace 记录"
                   "数都是 0**，连那条已有的路都还没有数据走过。先做没有数据"
                   "验证的第二条路，方向是反的。\n"
                   "**重新开的触发条件**（缺了这句，「容忍」和「拖着」从外面"
                   "看一模一样）：\n"
                   "  * 某个视图开始跨内核并排单条事件的指令号；或者\n"
                   "  * 某个指标的定义依赖「函数体跑完之后」的状态"
                   "（`allocated_pa` 就是这一类，它在等 nftrace 而不是在等"
                   "出口观察点）；或者\n"
                   "  * 语料里出现第一份 nftrace 记录数非 0 的录制 —— 那时"
                   "「入口看不到的东西」才第一次真的有数可对。",
    },
)

RESOLVED_DECLINED: tuple[dict[str, object], ...] = (
    {
        "group": "H 通用的锁词（alien 的 before_lock/after_lock 提出来的）",
        "kinds": ("lock.acquire", "lock.release"),
        "proposed_for": "alien：ksync 的 `before_lock` / `after_lock` 各 168 次，"
                        "是 alien-shell 那趟命中最多的两个观察点",
        "measured": (
            ("它们不是加锁解锁，是关中断开中断",
             "ksync/src/lib.rs：`before_lock() { push_off() }`、"
             "`after_lock() { pop_off() }` —— 就是 xv6 那对中断嵌套计数器。"
             "所以 168/168 相等是**配对**，不是巧合"),
            ("它们说不出是哪把锁",
             "签名 `fn before_lock()` 零参数（kernel-sync 4483c08 src/lib.rs:31-32）。"
             "而表里已有的锁词都带身份：`inode.lock` 带 resource、"
             "`syscall.mutex_lock` 带 mutex id。加一个没有操作数的 `lock.acquire`，"
             "跨内核就只能比次数 —— 而锁的粒度各家差一个数量级，次数恰恰"
             "是最不该跨内核比的东西"),
            ("只会有一个消费者",
             "全语料扫过真·锁函数：xv6 的 ilock/iunlock 已映 inode.lock/unlock；"
             "rCore 的 sys_mutex_lock/unlock 已映 syscall.mutex_lock/unlock；"
             "Starry 只有 fcntl_setlk/flock_op 那两个文件锁闭包。"
             "`lock.*` 这一族只会有 alien 一个用户"),
            ("同一个形状 xv6 早就量过并选了 skip",
             "xv6.toml 里 mycpu/cpuid 躲在 push_off/pop_off 后面 —— **和这里是"
             "同一对函数** —— 空跑到 idle shell 打了 179,801,344 次、"
             "占全部命中的 99.9%，结论是 skip 而不是 throttle"),
        ),
        "why": "第三条是登记处的规矩（共享词汇要有 ≥2 个消费者），但**不是"
               "主要理由** —— 只有一个用户的词可以先放着等第二个。真正致命的是"
               "第二条：这个词就算加了也带不出锁的身份，于是它唯一能支持的比较"
               "就是次数比较，而次数是这里最不可比的量。也就是说加了词也解决不了"
               "提出它的那个问题。\n"
               "第一条则说明连名字都是误导的：叫 `lock` 的东西干的是中断嵌套"
               "计数，映成 `lock.acquire` 会把「关中断」记成「取锁」。",
        "decided": "**不加词，两个函数留在 `func.*`，而且暂不 skip。**\n"
                   "不 skip 的理由是量出来的：这趟 34% 还没到淹没的地步"
                   "（分母是 993 条 watch 事件，336/993 = 33.8%）。"
                   "换个真跑得起来的负载它大概率要单独 skip —— 那是节流的事，"
                   "不是词汇的事，两件事别混。\n"
                   "**重新开的触发条件**：\n"
                   "  * 拿得出一个**带锁身份**的观测方案（哪把锁、谁持有）—— "
                   "光加词解决不了第二条，所以没有这个方案就不必再提；或者\n"
                   "  * 出现第二个内核，它的锁函数带得出身份、且现有的 "
                   "`inode.lock` / `syscall.mutex_lock` 都罩不住它 —— "
                   "那时才同时满足「带得出身份」和「≥2 个消费者」。",
    },
)

RESOLVED_DISTINCT: tuple[dict[str, object], ...] = (
    {
        "group": "B Rust 分配失败（原 UNRESOLVED B 组；"
                 "2026-09-03 改撞词，2026-09-04 反汇编定粒度）",
        "kinds": ("kernel.alloc_error", "panic.alloc", "panic.alloc_handler"),
        "measured": (
            ("rcore", "alloc::alloc::handle_alloc_error 0x80212728",
             "jalr -> 0x8020e1f0", "panic.alloc（未映）"),
            ("rcore", "__rust_alloc_error_handler 0x8020e1f0",
             "8 字节纯跳板，jr -> 0x80209e18", "panic.alloc_handler"),
            ("rcore", "__rg_oom 0x80209e18",
             "jalr -> 0x80209dbe", "未映（local + .hidden，选不中）"),
            ("rcore", "os::mm::heap_allocator::handle_alloc_error 0x80209dbe",
             "内核自己的 #[alloc_error_handler]", "kernel.alloc_error"),
            ("arceos", "alloc::alloc::handle_alloc_error 0xffffffc080212c16",
             "jalr -> 0xffffffc0802005ca", "panic.alloc"),
            ("arceos", "__rust_alloc_error_handler 0xffffffc0802005ca",
             "8 字节纯跳板，jr -> 0xffffffc080212b6a", "panic.alloc_handler"),
            ("arceos", "__rdl_alloc_error_handler 0xffffffc080212b6a",
             "jalr -> core::panicking::panic_nounwind_fmt，不回内核", "未映"),
        ),
        "why": "**先更正一句旧话：rCore 是四个符号，不是三个。**原来那张三层表"
               "是从录下来的 watchlist.json 读的，而 `__rg_oom` 是 local + "
               "`.hidden`，选点规则选不中，从来没进过 watchlist。"
               "**从选中的东西里推不出总共有什么** —— 跟 #87 那次"
               "（`select_watchlist` 返回空被当成「找不到」）是同一个坑。\n"
               "原来打算等一趟真 OOM 再裁，那是把一个**静态**问题当成了动态"
               "问题：「1→2→3 是不是调用链」写在 `.text` 里，反汇编就读得出来，"
               "不需要它跑起来。把触发条件写成「等录到一次 OOM」，等于给一个"
               "查得到的事实设了个永远不会到的期限。\n"
               "读出来两件事：\n"
               "**一、是调用链，而且 1:1。**每条边都是无条件直接跳转，没有间接"
               "调用也没有条件分支，一次分配失败每层各响一次。所以光看计数取哪"
               "一层都一样 —— 这一层的选择不是精度问题，是含义问题。\n"
               "**二、第 3 层不是「一层」，是个岔路口。**`__rg_oom` 只在 crate "
               "定义了 `#[alloc_error_handler]` 时生成；没定义就生成 "
               "`__rdl_alloc_error_handler` 那条默认路，直接 panic 不回内核。"
               "一个 crate 只会有其中一个。所以 rCore 的四层和 ArceOS 的三层"
               "不是同一条链上深浅不同的两个位置，是分叉后的两条路。",
        "changed": "**没改任何映射** —— 裁决确认的正是现状。"
                   "`panic.alloc_handler`（第 2 层）已经是两边共用的词，"
                   "2026-09-03 改撞词那次就顺手对齐了。",
        "consequence": "**跨内核比第 2 层 `__rust_alloc_error_handler` "
                       "（`panic.alloc_handler`）。**三条理由，第三条最重要：\n"
                       "  一、它在岔路**上游**，两边都有，含义相同；\n"
                       "  二、它是 Rust ABI 定死的接缝，8 字节跳板的形状"
                       "两边一模一样；\n"
                       "  三、因此**任何 no_std + 全局分配器的 Rust 内核都必然"
                       "有它** —— starry / axvisor / alien 不用各写一条规则"
                       "就能对上。可比性来自结构，不来自逐内核的手工对齐。\n"
                       "第 1 层和第 4 层留着，但不可比，而且原因不同：第 1 层是"
                       "「库发现失败了」（语言运行时的视角），第 4 层是「这个"
                       "内核自己的处置跑了」（内核策略的视角）。第 4 层在 ArceOS "
                       "上不存在**不是没映射，是它没定义自己的处理函数** —— "
                       "而这件事本身静态可读：看 `.text` 里是 `__rg_oom` 还是 "
                       "`__rdl_alloc_error_handler`，就知道这个内核有没有自己的 "
                       "OOM 策略。\n"
                       "`__rg_oom` / `__rdl_alloc_error_handler` 两边都不映：映了"
                       "只会多一个恒等于第 2 层的计数（1:1 已经证了），而它真正"
                       "携带的信息是静态的，不该靠事件去读。",
        "why_zero": "三个词全语料 0 次 —— 它们挂在分配失败路径上，出现即意味着"
                    "内核堆爆了，而语料里没有爆过的录制。"
                    "（rcore-ch6-fs 控制台那句 `Heap allocation error` 是"
                    "**用户态**堆：`stdio.rs` 判空用 `if c == 0`，OpenSBI 取不到"
                    "字符返回 -1，0xFF 灌满 8KB 用户堆。内核分配器全程没出过错。）\n"
                    "**以后有哪趟真 OOM 了，四层计数应该全相等；不相等就是这条"
                    "结论错了**，回来重读这一组。",
    },
    {
        "group": "E 映射页面（原 UNRESOLVED E 组；2026-09-03 读源码裁决，同日改完）",
        "kinds": ("pagetable.map", "pagetable.unmap", "vm.map", "vm.unmap"),
        "measured": (
            ("xv6",    "mappages(pt, va, size, pa, perm)",
             "for(;;){ walk(); *pte=...; a += PGSIZE; }",       "区域"),
            ("arceos", "Backend::map(start, size, flags, pt)",
             "PageIter4K::new(start, start+size) 逐页 cursor().map()", "区域"),
            ("rcore",  "PageTable::map(vpn, ppn, flags)",
             "find_pte_create(vpn); *pte = ...  就一个 PTE",     "单页"),
        ),
        "why": "结论跟原来猜的方向不一样：**分错的不是 ArceOS。** 真正的分界"
               "是「区域」对「单个 PTE」，而这条线横切了现有的名字 —— xv6"
               "（区域）和 rCore（单页）共用 pagetable.map，ArceOS（区域，"
               "跟 xv6 同级）反倒单用 vm.map。",
        "consequence": "`page_table_maps` 这个指标在两种粒度上数数，而且"
                       "**已经在数了** —— 不是将来会出问题：\n"
                       "    lab3-cowtest-mac  76583  全来自 mappages（区域）\n"
                       "    rcore-watchtest   32318  全来自 PageTable::map（单页）\n"
                       "两个数各自都没数错，错的是顶着同一个名字并排摆出来："
                       "读的人会拿 76583 和 32318 比，而那是「映射了多少段」"
                       "对「写了多少个 PTE」。\n"
                       "**这一条 2026-09-03 更正过。**原来写的是"
                       "「眼下没数错 —— rcore-ch6-fs 那趟一个观察点都没挂上，"
                       "报的是 None。是运气，不是设计」。运气那半句说对了，"
                       "「没数错」那半句是拿一趟当全部：八趟 rcore 逐个量下来，"
                       "watchtest 那趟是有数的，其余七趟才是 None。",
        "changed": "**已改（#70）。**pagetable.map 收窄成「写一个 PTE」，区域级"
                   "归 vm.map —— xv6 的 mappages/uvmunmap 从 pagetable.* 挪到 "
                   "vm.*，于是 xv6 跟 ArceOS 站到一起，那正是量出来的分组。\n"
                   "指标同步拆成两档：vm_maps / vm_unmaps 数「映射了多少段」，"
                   "page_table_maps 数「写了多少个 PTE」。\n"
                   "`page_table_unmaps` 这条指标顺势删了 —— xv6 的 uvmunmap 挪走"
                   "之后，七份 manifest 没有一份再声明 pagetable.unmap，它对谁"
                   "都是 None。删的是指标不是词：那个词还登记着，因为 rcore.toml "
                   "明写着自己缺这一条「不是漏写的」。\n"
                   "改基准输出这件事的实际代价（量过，不是估的）：\n"
                   "    lab3-cowtest-mac  76583 从 page_table_maps 搬到 vm_maps，"
                   "page_table_maps 变 None —— xv6 没有单 PTE 那一档的观察点\n"
                   "    rcore-watchtest   32318 留在 page_table_maps，没动\n"
                   "**一个数都没丢**，改的是它叫什么、跟谁可比。\n"
                   "顺带堵上一个洞：ArceOS 一直有 vm.map 事件，可原来没有任何"
                   "指标收它，报告读起来像个从不映射页面的内核。现在报 vm_maps=1。",
    },
    {
        "kinds": ("sched.yield", "sched.yield_to_scheduler"),
        "why": "xv6 里 yield 和 sched 是两个真函数，而且是一前一后："
               "yield 把自己置成 RUNNABLE 再调 sched，sched 才做切换。"
               "xv6 的 manifest 两个都映了。不是拼法之争。",
    },
    {
        "kinds": ("heap.alloc", "phys.alloc"),
        "why": "heap.* 是 Rust 的全局分配器（ArceOS 的 __rust_alloc 一路），"
               "phys.* 是物理页帧分配器（xv6 kalloc / rCore frame_alloc）。"
               "一个发字节，一个发页帧，上下两层。别因为都叫 alloc 就并。",
    },
    {
        "kinds": ("trap.kernel", "trap.kerneltrap"),
        "measured": (
            ("xv6", "kerneltrap()  kernel/trap.c:185",
             "devintr() 认设备中断；which_dev==2 且时间片到了就 yield()；"
             "然后写回 sepc/sstatus **正常返回**。只有 devintr() 返回 0 "
             "（不是设备中断）才 panic",
             "常规路径", 274),
            ("rcore", "trap_from_kernel() -> !  os/src/trap/mod.rs:141",
             "无条件 panic!(\"a trap {:?} from kernel!\")。返回类型是 ! ，"
             "**根本不返回**",
             "致命路径", 0),
        ),
        "why": "名字都是「内核态陷入」，角色正好相反：xv6 的 kerneltrap 是"
               "**内核态处理设备中断的正常出入口**，处理完照常返回；rCore 的 "
               "trap_from_kernel 是**「这不该发生」的中止点**，进去就 panic。"
               "并到一个类别，等于把一条常规路径和一条崩溃路径算成一件事。\n"
               "**原来的 why 把方向说反了**：它说 xv6 那个是照函数名起的坏"
               "名字、rCore 那个是中性词，所以该并到 rCore 那个。读了源码才"
               "知道两者根本不是一件事，名字好坏无关 —— #51/#63 治的是"
               "「类别别照函数名起」，但这条规则**不能**推出「两个描述不同"
               "东西的词该合并」。",
        "why_zero": "这也解释了 274 对 0 的悬殊：**不是 rCore 没赶上，是"
                    "rCore 一旦赶上就崩了**。trap.kernel 的 0 是设计上的 0，"
                    "不是运气。旁证：kernel.panic 同样是 0，两个数互相对得上"
                    "（真进了 trap_from_kernel，这两条会一起出现）。",
    },
    {
        "kinds": ("interrupt.timer", "interrupt.clock"),
        "measured": (
            ("lab3-cowtest-mac", 419, 419, "严格一对一交错，相邻不同 837/837"),
        ),
        "why": "**这是五组里唯一两个词都真的出现过的一组，量下来是两个观察点，"
               "不是同义词。**\n"
               "在 xv6 的 lab3-cowtest-mac 那趟里，interrupt.timer 419 次、"
               "interrupt.clock 419 次，而且事件序列是 timer, clock, timer, "
               "clock … 严格交错（相邻两条不同的比例 837/837）。光数目相等还"
               "说明不了什么 —— 两件无关的事也可能都发生 419 次；**交错才是"
               "决定性的**：一次时钟中断先被按 scause=5 解出来（interrupt."
               "timer），再进 clockintr（interrupt.clock）。一次中断，两个"
               "观察点。\n"
               "所以并掉是错的：并了 timer_interrupts 会从 419 变成 838。"
               "现在 _METRIC_KINDS 里 timer_interrupts 只认 interrupt.timer，"
               "数出来 419，是对的 —— **这一组不需要改任何东西**。",
    },
    {
        "kinds": ("trap.page_fault", "trap.page_fault_handler"),
        "measured": (
            ("starry-forkecho", 351, 351,
             "严格一对一交错，相邻二元组 (fault,handler) 351 / "
             "(handler,fault) 350；fault->handler 的指令间隔只有两个取值："
             "间隔 2166 出现 331 次、间隔 2113 出现 20 次（合计 351）"),
            ("starry-fsprobe", 323, 323,
             "**独立第二趟**，同样严格一对一交错（323 / 322），而且指令间隔是"
             "**同样那两个值**：2166 出现 306 次、2113 出现 17 次（合计 323）。"
             "注意这趟里后一个词的标签是 `func.handle_user_page_fault` 而不是 "
             "`trap.page_fault_handler` —— kind 是录制期烧进去的，这趟录于 "
             "00:11，早于 starry.toml 加上那条 [event] 映射（forkecho 录于 "
             "03:46）。同一个观察点、同一个 ELF（starry-1f85a279）、同一个 "
             "watch_source，只是标签不同"),
        ),
        "why": "**等到数据的不是 arceos，是 Starry。**这一组原来卡在"
               "「arceos 那五趟连代码解出来的事件都没有」，重开条件写的也是"
               "「等某趟 arceos 产出任何一条代码解出来的事件」。实际解开它的是"
               "另一个内核：starry.toml 把 `handle_user_page_fault` 映成了 "
               "trap.page_fault_handler，于是 starry-forkecho 这一趟里**两个词"
               "都有输出**，各 351 次。\n"
               "交错法的结论和 F 组一样，而且比 F 组更硬，硬在两处：\n"
               "一是**指令间隔是固定的**（2166 或 2113，两个确定值，没有第三"
               "个）。间隔恒定说明后一条不是另一次缺页，是同一次缺页走到了下一"
               "层 —— 先按 CSR 解出来，再进处理函数。一次缺页，两个观察点。"
               "两个值大概率对应两条进处理函数的路径（这趟的 fault_kind 有 "
               "store 等多种），但**具体哪条对哪个没量**，别当结论用。\n"
               "二是**两趟独立复现**：starry-fsprobe 也是严格交错，而且间隔"
               "还是 2166/2113 这同两个值。F 组当初只有一趟。\n"
               "所以并掉是错的：并了 page_faults 会从 351 变成 702。现在 "
               "_METRIC_KINDS 里 page_faults 只认 trap.page_fault，"
               "在 starry-forkecho 上实测读出 351 —— **这一组不需要改任何东西**。",
        "still_open": "**裁掉的是词汇问题，不是 arceos 问题。**「这两个词是不是"
                      "同一件事」已经定了（不是），这条结论对整张表生效。"
                      "但「ArceOS 缺页时到底走不走 handle_page_fault 这一层」"
                      "仍然没量 —— 那五趟 arceos 至今一条代码解出来的事件都没有。"
                      "那是另一个问题：它问的是某个内核有没有这一层，不是两个词"
                      "该不该并。C 组原文里就写着这两者「不是同一个问题的答案」。",
    },
)

#: trap.exception / trap.unknown）。
UNDECIDABLE_FROM_TRACES: frozenset[str] = frozenset()

RETIRED: dict[str, str] = {
    "panic.enter": (
        "2026-09-03 并进 `kernel.panic`（RESOLVED_MERGED A 组）。同一个 Rust "
        "lang item，xv6 和 rCore 都叫 kernel.panic，而 kernel.panic 有四个消费者"
        "（app.js 的标记和详情、video.py 的关键帧和**崩溃判定**），panic.enter "
        "一个都没有 —— ArceOS 真崩一次会全程静默。并的时候它全语料 0 次。"
    ),
    "trap.pagefault": (
        "2026-09-03 改名 `trap.page_fault_handler`（原 UNRESOLVED C 组，"
        "2026-09-07 裁进 RESOLVED_DISTINCT：两层不并）。"
        "老名字跟 `trap.page_fault` 只差一个下划线，看着像打错字，"
        "实际是两层不同来源：前者代码按 CSR 解，后者 arceos.toml 映的处理"
        "函数。改名时它全语料 0 次，所以动不了任何数字。"
    ),
    "vm.push_area": (
        "2026-09-03 并进 `vm.map`。它是照着 rCore 的函数名 `MemorySet::push` "
        "拼出来的私有词，消费者为零，而 `vm.map` 有 `vm_maps` 指标 —— rCore "
        "一直在产生区域级映射事件，指标栏里却写着「未观测」。粒度按 #70 那条线"
        "核过：push → MapArea::map → 逐页 PageTable::map，正是「一次调用映射"
        "一段」。理由写在 rcore.toml 那一条上面。"
        "\n\n"
        "**跟前两条不一样：退役时它不是 0 次。** 语料里有三份录制的 watchlist "
        "写着这个词（rcore-watchtest / forktest / filetest）。分析读的是**录制"
        "当时**那份 watchlist 的 kind，不是现在的 manifest，所以那三趟会一直"
        "报 vm.push_area、`vm_maps` 一直是 None —— 那不是 bug，是它们录的时候"
        "这个词就是这么定的。要让 rCore 的 vm_maps 有数，得**重录**（重录不是"
        "重编：ELF 不变，见 rcore.toml 的 build_deviation）。"
    ),
}


class UnknownKindError(ValueError):
    pass


def is_registered(kind: str) -> bool:
    return (kind in KINDS
            or any(kind.startswith(p) for p in GENERATED_PREFIXES))


def check(kind: str, where: str) -> None:
    if is_registered(kind):
        return
    near = sorted(k for k in KINDS if k.split(".")[0] == kind.split(".", 1)[0])
    hint = ("；这个命名空间下已登记的有：" + "、".join(near)) if near else ""
    raise UnknownKindError(
        f"{where} 用了没登记的事件类别 {kind!r}。类别是跨内核共用的词汇，"
        f"新词要先加进 nodefusion/model/kinds.py 的 KINDS —— 加之前先看看"
        f"是不是已经有人给同一件事起过名字了（那正是这张表要拦的）"
        f"{hint}。")
