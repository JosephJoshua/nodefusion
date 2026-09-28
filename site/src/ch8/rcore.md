# rCore 实现

源码固定到 [`00b2a84`](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/tree/00b2a84360710640fbde595c194a7f2447e755f2) 的 `ch8-api-impl`。线程与同步对象分别位于 `os/src/task/` 和 `os/src/sync/`。

## 进程与线程

[`ProcessControlBlock`](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/blob/00b2a84360710640fbde595c194a7f2447e755f2/os/src/task/process.rs) 保存地址空间、文件描述符表、线程列表、同步对象列表与资源分配检查器。[`TaskControlBlock`](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/blob/00b2a84360710640fbde595c194a7f2447e755f2/os/src/task/task.rs) 保存进程的弱引用、自身的上下文、状态、退出码和线程资源。编译后的两个结构分别为 288 字节和 184 字节。

每个线程分配独立的用户栈、内核栈与异常上下文页。用户栈大小为 8 KiB，相邻用户栈之间留 4 KiB 间隔。线程共享进程地址空间，所以一个线程写入的普通用户变量可由同进程其他线程读取。文件描述符和同步对象也属于进程。

## 创建、退出与等待

[`sys_thread_create`](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/blob/00b2a84360710640fbde595c194a7f2447e755f2/os/src/syscall/thread.rs) 分配 TID、线程资源和控制块，将入口地址写入新线程的异常上下文，把参数写入 `a0`，最后加入就绪队列。返回的是进程内的 TID。

线程退出时，`TaskUserRes` 被释放：用户栈和异常上下文页解除映射，TID 随之回收。退出状态仍留在线程控制块中，直到 `waittid` 取走对应槽位。因而 TID 可能早于 `waittid` 被再次分配；分析生命周期时还要看线程控制块的引用。

`waittid` 对自身或空槽返回 `-1`，对尚未退出的线程返回 `-2`，对已退出的线程返回退出码。当前实现直接按 TID 索引线程列表，越界并不走上述错误返回路径。`fork` 和 `exec` 都检查进程线程列表长度为 1；这个检查与“只有一个线程正在运行”不同。

## 调度、阻塞与唤醒

就绪队列按 FIFO 取线程。主动让出时，当前线程重新加入就绪队列；阻塞时，当前线程离开就绪队列，等待同步对象或定时器唤醒。[`block_current_and_run_next`](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/blob/00b2a84360710640fbde595c194a7f2447e755f2/os/src/task/mod.rs) 和 `wakeup_task` 分别完成这两端的状态改变。

切换先保存当前线程上下文，回到处理器的空闲上下文，再选择下一个线程。运行报告中的切换事件也沿这两个方向记录。查看一个线程的活动时，可以结合进程 PID、线程对象和函数调用链，不只看 TID 数字。

## 互斥锁

[`MutexSpin`](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/blob/00b2a84360710640fbde595c194a7f2447e755f2/os/src/sync/mutex.rs) 在锁已占用时调用 `suspend_current_and_run_next`，下一次运行再检查；线程仍在就绪队列中。`MutexBlocking` 则把等待者放入 FIFO 队列，并调用阻塞调度路径。

阻塞锁解锁时，若队列非空，内核先把资源归属记给队首线程，再唤醒它。`locked` 保持为 `true`，被唤醒的 `lock` 从原调用位置返回。只有队列为空时，解锁才将 `locked` 改为 `false`。

用户程序 `ch8b_race_adder_mutex_spin` 创建 16 个工作线程，每个线程对共享计数器执行 1000 次更新；完整临界区包含读取、加一和写回，最后检查 16000。

## 信号量与条件变量

[`Semaphore`](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/blob/00b2a84360710640fbde595c194a7f2447e755f2/os/src/sync/semaphore.rs) 的有符号 `count` 表示可用许可数；为负时，其绝对值对应等待线程数。`down` 先减一，结果为负便排队阻塞。`up` 加一，结果仍小于等于零便把许可交给队首线程，唤醒后的 `down` 不再次减数。

[`Condvar::wait`](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/blob/00b2a84360710640fbde595c194a7f2447e755f2/os/src/sync/condvar.rs) 释放传入的互斥锁，把当前线程加入条件变量队列，然后阻塞。`signal` 从队首唤醒一个线程，不保存额外通知。线程恢复后调用 `mutex.lock()`；这个调用也可能再次阻塞。用户程序用 `while` 检查共享条件。

`ch8b_test_condvar` 的一个线程通过 `sleep_blocking(10)` 使用内核定时器，另一个线程等待共享变量改变。信号量测试以 0 个许可启动，由一个线程 `up` 通知另一个线程继续。

## 资源检查与接口参数

进程分别为互斥锁与信号量维护一个 [`DeadlockDetector`](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/blob/00b2a84360710640fbde595c194a7f2447e755f2/os/src/sync/deadlock.rs)。它记录每个资源当前可用数量、每个线程已持有的数量，以及每个线程当前等待的一个资源。`is_safe` 用一份可用数量副本寻找能够完成的线程，将它已持有的资源加入副本，反复进行直到全部完成或再无进展。

启用检查后，危险请求在修改锁或信号量的计数与队列之前被拒绝，系统调用返回 `-0xDEAD`。互斥锁和信号量使用各自的检查器；该实现记录的是当前请求，不保存线程未来可能申请的最大数量。

同步对象由进程持有。系统调用从对象列表中按编号取对象，部分路径直接索引或 `unwrap`；越界参数可能触发内核 panic。阅读调用者时应结合具体接口检查编号。

## 运行观察

基础批次执行 `ch8b_usertest`，20 个课程测试全部按预期退出。原始流记录 36 次线程创建与 36 次线程完成；`sys_waittid` 进入 1336 次，其中包含等待期间的重复查询。自旋互斥锁的 `lock`、`unlock` 各进入 16000 次，对应共享计数器用例的更新次数。

| 观察点 | 基础批次 | 扩展批次 |
| --- | ---: | ---: |
| 完成的线程 | 36 | 43 |
| 物理页分配 / 归还 | 1889 / 1776 | 2602 / 2489 |
| 使用页数峰值 / 结束值 | 932 / 113 | 1576 / 113 |
| 原始语义事件 | 6,529,623 | 6,756,857 |

扩展批次运行 `ch8_usertest`，23 个课程测试全部按预期退出，包含互斥锁与信号量的资源分配检查用例。原始流中 `sys_enable_deadlock_detect` 进入 3 次，完成的线程为 43 个。两份交互报告各保留 150000 条语义事件供浏览；表中的计数来自完整原始流。

在函数视图搜索 `sys_thread_create`、`sys_waittid`、`MutexSpin::lock`、`MutexBlocking::lock`、`Condvar::wait`、`Semaphore::down`，查看线程创建与同步调用。结合 PID、线程创建事件与两段调度切换，追踪单个线程从就绪、阻塞到唤醒的路径。扩展批次可以继续搜索 `sys_enable_deadlock_detect` 与 `is_safe`。

[打开基础测试报告](../reports/rcore/ch8/2026a/rcore-2026A-ch8-basic-observed-v3.html) · [打开扩展测试报告](../reports/rcore/ch8/2026a/rcore-2026A-ch8-extended-observed-v3.html)

<details><summary>构建与录制参数</summary>

用户程序固定到 [`a059366`](https://github.com/LearningOS/rCore-Tutorial-Test/tree/a0593662ad55d670ba8c27ce1763347cd0dd552f)。观察版应用 `nodefusion/integrations/rcore-2026a-ch8-observation.patch`。84 个用户 ELF 与参考构建逐字节相同。

录制使用 QEMU 10.2.2 和 `--no-build --function-returns --watch-all --profile uniform --snapshots 80 --max-ram-bytes 268435456 --timeout 600 --no-render --event-stream never`。基础、扩展批次的 `--program` 分别为 `ch8b_usertest`、`ch8_usertest`。完整命令、源码版本、补丁、构建产物、初始磁盘与原始轨迹校验值见[基础记录](../reports/rcore/ch8/2026a/recording.json)和[扩展记录](../reports/rcore/ch8/2026a/rcore-2026A-ch8-extended-observed-v3.json)。

</details>
