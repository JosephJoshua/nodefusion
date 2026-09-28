# uCore 实现

源码固定到 [`9d4fa96`](https://github.com/LearningOS/uCore-Tutorial-Code-2026A/tree/9d4fa96b67b449bc72f6530286b5a438e9de3ce5) 的 `ch8-api-impl`。进程与线程结构位于 `os/proc.h`、`os/proc.c`，同步对象位于 `os/sync.h`、`os/sync.c`。

## 进程与线程

[`struct proc`](https://github.com/LearningOS/uCore-Tutorial-Code-2026A/blob/9d4fa96b67b449bc72f6530286b5a438e9de3ce5/os/proc.h) 保存地址空间、文件描述符表、同步对象池及 16 个线程槽；全局进程表有 128 个槽。[`struct thread`](https://github.com/LearningOS/uCore-Tutorial-Code-2026A/blob/9d4fa96b67b449bc72f6530286b5a438e9de3ce5/os/proc.h) 保存 TID、所属进程、状态、上下文与栈位置。编译后的进程结构大小为 4992 字节。

每个线程有独立的用户栈、内核栈和异常上下文。三者各占一页。内核栈与异常上下文的存储来自静态数组；用户栈由线程创建路径映射到进程地址空间。线程共享同一进程的用户内存、文件和同步对象。

## 创建、退出与等待

[`sys_thread_create`](https://github.com/LearningOS/uCore-Tutorial-Code-2026A/blob/9d4fa96b67b449bc72f6530286b5a438e9de3ce5/os/syscall.c) 调用 `allocthread` 取得空闲槽，为新线程设置入口、参数 `a0` 与用户栈，然后置为 `RUNNABLE` 并加入任务队列。没有可用槽时返回 `-1`。

线程退出路径解除用户栈映射，保存退出码。`waittid` 检查 TID 范围、自身与槽位状态；目标仍在运行时返回 `-2`，已退出时取得退出码并通过 `freethread` 回收槽位。TID 在此之后才可由新的 `allocthread` 复用。

本章的 `fork` 为子进程建立主线程并复制它的异常上下文，没有 rCore 中检查线程列表长度为 1 的断言。分析父子进程时仍需区分新 PID 与进程内 TID。

## 调度、阻塞与唤醒

调度器从就绪队列按 FIFO 选择 `RUNNABLE` 线程。`yield` 将当前线程重新入队；阻塞锁、信号量和条件变量把线程设为 `SLEEPING`，然后调用 `sched`。唤醒路径把线程改为 `RUNNABLE` 并入队。

`swtch` 在当前线程和调度器上下文之间切换。一次从线程 A 运行到线程 B 的过程包含 A 返回调度器、调度器进入 B 两条边。进程的文件与地址空间仍保持共享，切换的是线程自己的内核执行上下文。

## 互斥锁

[`mutex_lock`](https://github.com/LearningOS/uCore-Tutorial-Code-2026A/blob/9d4fa96b67b449bc72f6530286b5a438e9de3ce5/os/sync.c) 遇到已占用的自旋锁时反复 `yield`；阻塞锁则把线程编号放入 FIFO 等待队列，将线程设为 `SLEEPING`。锁空闲时，直接将 `locked` 设为 1。

阻塞锁解锁时，从队列取出一个线程并使其可运行；`locked` 仍为 1，锁已交给该线程。若队列为空，才将 `locked` 设为 0。被唤醒的 `mutex_lock` 沿原来的调用返回，不再次竞争一次。

课程程序 `ch8b_mut_race` 创建 15 个工作线程，每个线程更新共享计数器 100 次，最后检查 1500。主线程也占用 16 个线程槽中的一个。

## 信号量与条件变量

[`semaphore_down`](https://github.com/LearningOS/uCore-Tutorial-Code-2026A/blob/9d4fa96b67b449bc72f6530286b5a438e9de3ce5/os/sync.c) 将 `count` 减一。负数表示已有线程等待；调用者加入 FIFO 队列后睡眠。`semaphore_up` 加一，若结果仍小于等于零，就唤醒一个等待者。被唤醒的 `down` 从原位置继续，不再次减数。

[`cond_wait`](https://github.com/LearningOS/uCore-Tutorial-Code-2026A/blob/9d4fa96b67b449bc72f6530286b5a438e9de3ce5/os/sync.c) 先解锁，再入条件变量队列并睡眠；恢复后重新调用 `mutex_lock`。`cond_signal` 唤醒队首线程，不保存无人接收的通知。课程程序在循环中检查共享条件。

`ch8b_test_condvar` 使用用户库的 `sleep(10)`，由 `get_mtime` 与 `yield` 循环实现。它没有经过本章内核定时睡眠路径。

## 资源检查与接口参数

每个进程预留 8 个互斥锁、8 个信号量和 8 个条件变量槽。创建时分配下一个编号，没有销毁接口；达到上限时创建返回 `-1`。等待队列最多容纳 16 项。同步对象编号无效时，相关系统调用返回 `-1`。

本章源码在 `syscall.c` 留有资源分配检查的练习位置，系统调用分派中没有对应处理分支。互斥锁与信号量执行前面的等待和唤醒逻辑，不进行 rCore 那种请求安全性检查。

## 运行观察

以 `ch8b_usertest` 启动课程批次，官方正向检查的 23 项全部通过。原始流记录 50 次线程创建与完成；`sys_waittid` 进入 21386 次，其中包含等待线程退出时的重复查询。`mutex_lock`、`mutex_unlock` 各进入 10963 次，`semaphore_down`、`semaphore_up` 各进入 1601 次，`cond_wait`、`cond_signal` 各进入 1 次。

| 观察点 | 课程批次 |
| --- | ---: |
| 完成的线程 | 50 |
| 物理页分配 / 归还 | 795 / 724 |
| 使用页数峰值 / 结束值 | 135 / 71 |
| 原始语义事件 | 18,298,814 |

交互报告保留 150000 条语义事件，表中计数来自完整原始流。物理页数据对应 `kalloc` 与 `kfree`；每线程静态内核栈及异常上下文不经过这两个函数。

在函数视图搜索 `sys_thread_create`、`allocthread`、`mutex_lock`、`semaphore_down`、`cond_wait` 和 `cond_signal`，查看同步调用与线程状态。调度事件分别记录线程离开处理器和下一个线程进入处理器的路径。

[打开课程测试报告](../reports/ucoreos/ch8/2026a/ucore-2026A-ch8-basic-observed.html)

<details><summary>构建与录制参数</summary>

用户程序固定到 [`1733f46`](https://github.com/LearningOS/uCore-Tutorial-Test/tree/1733f460c596b013b1c509ad42afa428640783b0)。观察版使用 `ucore-2026a-build.patch` 和 `ucore-2026a-ch8-observation.patch`；35 个用户程序与参考构建逐字节相同。工具版本为 GCC 14.2.0、CMake 3.31.6、QEMU 10.2.2。

录制使用 `--no-build --function-returns --watch-all --profile uniform --snapshots 80 --max-ram-bytes 268435456 --timeout 600 --no-render --event-stream never`。实际构建与录制命令、源码版本、补丁、用户程序、磁盘与原始轨迹校验值见[课程记录](../reports/ucoreos/ch8/2026a/recording.json)。

</details>
