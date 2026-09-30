# rCore 实现

第五章引入进程：每个进程拥有独立地址空间和 PID，调度器通过就绪队列选择运行对象。以下分析对应 [2026A 第五章参考实现](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/tree/023a5a0885fed8ae999406f17a494777c3e59af1)。

## 进程与调度器

[`TaskControlBlock`](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/blob/023a5a0885fed8ae999406f17a494777c3e59af1/os/src/task/task.rs) 保存 PID、内核栈和可变的进程状态。状态中包括地址空间、异常上下文、任务上下文、调度参数及父子关系。父进程以 `Arc` 持有子进程；子进程用 `Weak` 指回父进程。

就绪队列保存等待运行的进程。调度器取出一个进程，将它设为 `Running`，再从处理器的空闲上下文切换过去。进程让出处理器时重新入队，并切回空闲上下文。初始用户进程 `INITPROC` 拥有 PID 0；空闲上下文是调度器执行时使用的内核上下文。

## fork 与地址空间

[`fork`](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/blob/023a5a0885fed8ae999406f17a494777c3e59af1/os/src/task/task.rs#L209) 为子进程分配 PID、内核栈和新的用户地址空间。`MemorySet::from_existed_user` 遍历父进程的区域，为子进程分配物理页并复制内容。子进程的异常上下文也由此复制，再把其中的内核栈指针改为子进程自己的栈顶。

父进程把新控制块加入 `children`。`sys_fork` 将子进程保存的 `a0` 设为 0，加入就绪队列，并把子 PID 返回给父进程。两者从同一条用户指令之后继续执行，通过返回值区分自己的身份。

## exec 与程序装载

`sys_exec` 根据用户传入的名字查找程序。找到 ELF 后，`exec` 建立新地址空间并替换旧地址空间，重置用户入口、用户栈和堆边界。PID、内核栈及父子关系保持不变。

`spawn` 直接根据目标 ELF 创建子进程。它分配新进程并装载目标程序，随后建立父子关系、加入就绪队列。与 `fork` 后再 `exec` 相比，这条路径省去了复制父进程旧地址空间的步骤。

## waitpid 与退出

进程退出时，内核记录退出码，状态改为 `Zombie`，释放用户数据页。控制块仍由父进程持有，以便随后读取退出码。退出进程的子进程转交给 `INITPROC`。

[`waitpid`](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/blob/023a5a0885fed8ae999406f17a494777c3e59af1/os/src/task/task.rs#L255) 查找指定 PID 的子进程；`-1` 表示任意子进程。没有匹配项返回 `-1`，匹配项尚未退出返回 `-2`，找到僵尸进程则移除它并返回 PID 与退出码。用户库遇到 `-2` 会让出处理器后重试。控制块的最后一个强引用释放后，剩余页表页、PID 和内核栈随对象析构。

## 调度策略

[`TaskManager::fetch`](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/blob/023a5a0885fed8ae999406f17a494777c3e59af1/os/src/task/manager.rs) 选择 `stride` 最小的就绪进程，同值时按入队顺序选择。每选中一次，便将该进程的 `stride` 增加 `65536 / prio`。

例如优先级 4 的增量是 16384，优先级 8 的增量是 8192。两者都持续就绪时，后者的 `stride` 增长较慢，会更频繁地得到处理器。`set_priority` 更改优先级时保留已经累积的 `stride`。

## 运行观察

基础报告中，PID 0 首先通过 `fork` 创建 PID 1，PID 1 随后执行 `exec`，成为 shell。shell 再创建测试进程。沿 `fork → exec → waitpid` 查看同一组 PID，可以把进程创建、程序替换和退出后的回收连起来。

扩展报告包含 `spawn` 和优先级测试。函数视图中选择 `TaskManager::fetch`，结合就绪进程的 `stride` 与 `prio`，可以核对每次选择后只更新被选中的进程。

[基础测试报告](../reports/rcore/ch5/2026a/rcore-2026A-ch5-basic-observed-v2.html) · [扩展测试报告](../reports/rcore/ch5/2026a/rcore-2026A-ch5-extended-observed-v2.html) · [录制数据](../reports/rcore/ch5/2026a/recording.json)
