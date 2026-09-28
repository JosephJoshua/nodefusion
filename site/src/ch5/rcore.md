# rCore 实现

源码固定到 [`023a5a0`](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/tree/023a5a0885fed8ae999406f17a494777c3e59af1) 的 `ch5-api-impl`。进程控制块与调度代码位于 `os/src/task/`，系统调用入口位于 `os/src/syscall/process.rs`。

## 进程与调度器

[`TaskControlBlock`](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/blob/023a5a0885fed8ae999406f17a494777c3e59af1/os/src/task/task.rs) 保存 PID、内核栈和可变的内部状态。内部状态包含 `MemorySet`、异常上下文物理页号、任务上下文、调度属性以及父子关系。

父进程用 `Vec<Arc<TaskControlBlock>>` 持有子进程，子进程用 `Weak` 指向父进程。这样，父进程可以保留已经退出的子进程，等待取得退出码；子进程的父指针不会增加父进程的强引用计数。

就绪队列持有 `Ready` 进程。调度器取出进程后，将其状态改为 `Running`，移入 `Processor.current`，再从 idle 上下文切换到进程的任务上下文。暂停时，内核取走 `current`，将进程设为 `Ready` 并重新入队，然后切回 idle。

idle 是调度器的执行上下文。初始用户进程 `INITPROC` 使用 PID 0，拥有自己的地址空间和内核栈；源码常量 `IDLE_PID` 指向这个初始用户进程。

## fork 与地址空间

[`TaskControlBlock::fork`](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/blob/023a5a0885fed8ae999406f17a494777c3e59af1/os/src/task/task.rs) 借用父进程状态，调用 `MemorySet::from_existed_user`。后者遍历父进程的区域，为子进程建立相同的区域与权限，分配独立物理页，再逐页复制内容。用户代码、数据、栈、堆、匿名映射和异常上下文都通过区域数组参与复制。

子进程取得新的 PID 与内核栈，任务上下文的返回地址设为 `trap_return`。复制得到的异常上下文中，`kernel_sp` 改为子进程内核栈顶，用户寄存器与 PC 保持父进程的值。新的调度属性为 `stride = 0`、`prio = 16`，子进程列表为空。

父进程将子进程的 `Arc` 加入 `children`。`sys_fork` 随后将子进程保存的 `a0` 改为零，把子进程加入就绪队列，向父进程返回新 PID。子进程被调度后直接经过异常返回进入用户态。

## exec 与程序装载

`sys_exec` 转换用户传入的程序名，查找嵌入的 ELF。名字不存在时返回 `-1`；查找成功后调用 `TaskControlBlock::exec`。

`exec` 先建立新的 `MemorySet`，再替换内部状态中的地址空间和异常上下文页号。原有地址空间随赋值释放。新的异常上下文包含程序入口、用户栈顶、内核页表、现有内核栈顶与异常处理函数；堆底和堆边界重设为新用户栈顶。PID、父子关系、内核栈和调度属性保留。

异常处理器调用系统调用后重新取得当前异常上下文，再写回返回值。`exec` 已经替换了异常上下文页，后续写回因此使用新页。

`spawn` 调用 `TaskControlBlock::new` 从目标 ELF 建立子进程，再注册父子关系。它直接分配目标程序的执行环境，省去复制父进程旧地址空间的过程。`sys_spawn` 将子进程入队，返回新 PID。

## waitpid 与退出

[`exit_current_and_run_next`](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/blob/023a5a0885fed8ae999406f17a494777c3e59af1/os/src/task/mod.rs) 从处理器取走当前进程，设为 `Zombie` 并保存退出码。子进程转交给 `INITPROC`，各子进程的父指针同时更新。`recycle_data_pages` 清空区域数组，释放其中持有的数据页。

此时，父进程仍持有僵尸进程的控制块。`PageTable.frames` 中的页表页也仍保留。区域数组清空时没有逐项清除 PTE，这张页表不会再次用于运行该僵尸进程。

`TaskControlBlock::waitpid` 按 PID 筛选子进程，`-1` 表示任意子进程。没有匹配的子进程时返回 `Err(-1)`；匹配的子进程仍未退出时返回 `Err(-2)`。成功时移除列表中的首个匹配僵尸，返回其 PID 与退出码。最后一个强引用释放后，剩余页表页、PID 和内核栈随对象析构回收。

`sys_waitpid` 仅在成功时向用户地址写入退出码。用户库遇到 `-2` 会调用 `yield` 后重试，所以用户调用可以等待到子进程退出。内核在退出路径中释放临时 `Arc` 和动态借用，再切回 idle；已退出进程的栈不会继续执行。

## 调度策略

[`TaskManager::fetch`](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/blob/023a5a0885fed8ae999406f17a494777c3e59af1/os/src/task/manager.rs) 在就绪队列中寻找最小的 `stride`，相等时按原有队列顺序选择。只给选中的进程增加 `65536 / prio`，再将它移出队列。状态改为 `Running` 和上下文切换由 `run_tasks` 完成。

例如优先级 4 和 8 分别得到增量 16384 和 8192。在持续就绪且每次运行都重新入队的条件下，较小的增量使进程更频繁地被选中。创建子进程会初始化新的调度属性，`exec` 则保留现有属性。

`set_priority` 接受所有不小于 2 的整数，修改优先级时保留已经累计的 `stride`。整数除法使大于 65536 的优先级得到零增量。这个边界可以用于检查调度选择与优先级接口之间的关系。

## 运行观察

两次录制分别从 shell 启动 `ch5b_usertest` 和 `ch5_usertest`。基础测试运行 11 个应用，扩展测试运行 19 个应用，包括进程创建、映射、优先级和 stride 调度测试。内核内嵌的 43 份用户 ELF 与参考构建逐一相同。

下表使用完整轨迹的统计。fork 次数来自记录父子 PID 的语义事件，其余函数次数按入口统计。

| 观察点 | 基础测试 | 扩展测试 |
| --- | ---: | ---: |
| fork 成功 | 55 | 2 |
| `exec` 入口 | 13 | 2 |
| `sys_spawn` 入口 | 0 | 68 |
| `sys_waitpid` 入口 | 97 | 8,903 |
| `sys_set_priority` 入口 | 0 | 12 |
| `recycle_data_pages` 入口 | 54 | 69 |
| `KernelStack::drop` 入口 | 54 | 69 |
| 物理页分配 | 1,365 | 1,469 |
| 物理页归还 | 1,259 | 1,363 |
| 分配器使用页数峰值 | 710 | 797 |
| 录制结束时分配器使用页数 | 106 | 106 |

基础测试的第一次 fork 位于指令计数 `26,710,023`，父 PID 为 0，子 PID 为 1。随后 PID 1 在 `26,767,015` 进入 `exec`。这是初始进程创建 shell 的路径。第二次 fork 在 `27,531,833` 创建 PID 2，PID 2 再执行测试程序。进程创建时的父子关系与后续 `exec` 的所属 PID 可以连续核对。

两份记录中，数据页回收与内核栈析构分别出现 54 次和 69 次。进入 `recycle_data_pages` 后可以沿物理页归还查看退出路径；进入 `KernelStack::drop` 时，再查看当前执行进程与被回收栈的编号，区分等待者和已经退出的子进程。PID 可以重用，识别一次进程生命周期还需结合创建与回收的先后顺序。

基础测试中的 `ch4b_sbrk` 在地址 `0xc000` 触发写访问缺页异常，以 `-2` 退出。扩展测试的 `ch4_mmap1` 和 `ch4_mmap2` 分别在 `0x10000000` 触发写、读访问缺页异常。这三次退出符合相应测试程序的预期，其余测试应用以零退出。

[打开基础测试报告](../reports/rcore/ch5/2026a/rcore-2026A-ch5-basic-observed-v2.html) · [打开扩展测试报告](../reports/rcore/ch5/2026a/rcore-2026A-ch5-extended-observed-v2.html)

函数视图可以搜索 `fork`、`exec`、`waitpid` 或 `KernelStack::drop`。事件视图按 PID 筛选，并结合 `proc.fork` 的父子 PID 查找对应操作。基础报告保留全部 127,198 条事件；扩展报告保留 150,000 条浏览样本，表中的计数来自完整轨迹。

<details>
<summary>构建与录制参数</summary>

用户程序固定到 [`a059366`](https://github.com/LearningOS/rCore-Tutorial-Test/tree/a0593662ad55d670ba8c27ce1763347cd0dd552f)。观察版使用 `rcore-2026a-ch5-observation.patch`，加入物理页、fork 和调度切换的语义记录，并保留相关函数入口。用户 ELF 从参考构建复制后，逐一检查实际嵌入镜像的字节。

Rust 工具链为 `nightly-2024-05-02`，QEMU 为 10.2.2。内核构建使用 `LOG=TRACE CARGO_PROFILE_RELEASE_DEBUG=2 cargo build --release --locked`。

录制使用 `--no-build --function-returns --watch-all --profile uniform --snapshots 80 --max-ram-bytes 268435456 --no-render --event-stream never`。基础测试使用 `--program ch5b_usertest --timeout 180`，扩展测试使用 `--program ch5_usertest --timeout 300`。测试结束后停止 shell 所在的 QEMU；录制结果按测试程序完成情况检查。

[基础测试记录](../reports/rcore/ch5/2026a/recording.json)与[扩展测试记录](../reports/rcore/ch5/2026a/rcore-2026A-ch5-extended-observed-v2.json)保存完整构建、录制和分析命令，以及源码补丁、内嵌用户 ELF、原始轨迹和报告的校验值。报告从同一份轨迹重新分析，使用语义切换中的 PID 更新后续事件归属，录制来源与分析来源分别保存。

</details>
