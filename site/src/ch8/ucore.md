# uCore 实现

第八章把调度单位从进程改为线程。同一进程中的线程共享用户地址空间和文件，却各自拥有执行栈与寄存器上下文。以下代码来自 [uCore 2026A 第八章](https://github.com/LearningOS/uCore-Tutorial-Code-2026A/tree/9d4fa96b67b449bc72f6530286b5a438e9de3ce5)。

## 进程与线程

[`struct proc`](https://github.com/LearningOS/uCore-Tutorial-Code-2026A/blob/9d4fa96b67b449bc72f6530286b5a438e9de3ce5/os/proc.h) 保存页表、文件描述符表、同步对象池和 16 个线程槽。[`struct thread`](https://github.com/LearningOS/uCore-Tutorial-Code-2026A/blob/9d4fa96b67b449bc72f6530286b5a438e9de3ce5/os/proc.h) 保存 TID、状态、调度上下文、内核栈和异常上下文。内核栈及异常上下文使用按进程槽和线程槽排列的静态数组；用户栈映射在所属进程的页表中。

线程之间共享同一地址空间，因而能直接访问相同的用户数据。切换线程时，`swtch` 更换的是线程自己的内核执行上下文；共享的页表和文件对象不因切换而复制。

## 创建、退出与等待

`sys_thread_create` 调用 `allocthread` 寻找空线程槽，为新线程映射用户栈与异常上下文页，设置入口地址和参数 `a0`，再把它加入就绪队列。16 个槽中已有一个供主线程使用，因此测试程序可以再创建 15 个工作线程。

线程调用 `exit` 时，`freethread` 解除该线程的用户栈和异常上下文映射，退出码保存在槽中，状态改为 `EXITED`。`waittid` 不阻塞：目标未退出时返回 -2；已退出时读取退出码、清空线程槽，使 TID 可以复用。编号无效、槽位未占用或等待自身时返回 -1。

`fork` 创建子进程后只建立主线程，复制父进程主线程的异常上下文。源码没有检查调用 `fork` 的是否为主线程；理解这条路径时，应注意它固定读取 `threads[0]`。

## 调度、阻塞与唤醒

调度器从就绪队列取出 `RUNNABLE` 线程。`yield` 将当前线程放回队尾；阻塞同步原语则把线程设为 `SLEEPING`，调用 `sched` 切回调度器。解锁或发出通知的线程把等待者改回 `RUNNABLE` 并入队。

线程 A 让出后到线程 B 开始运行，经过两次 `swtch`：一次保存 A 并恢复调度器，一次保存调度器并恢复 B。A 以后被选中时，从原来调用 `sched` 的地方继续。

## 互斥锁

[`mutex_lock`](https://github.com/LearningOS/uCore-Tutorial-Code-2026A/blob/9d4fa96b67b449bc72f6530286b5a438e9de3ce5/os/sync.c) 在锁空闲时直接设 `locked = 1`。若锁已占用，自旋型互斥锁反复调用 `yield`；阻塞型互斥锁把线程放入 FIFO 等待队列并设为 `SLEEPING`。

阻塞型互斥锁解锁时，若有人等待，就让队首线程运行，同时保持 `locked = 1`。锁的持有权直接交给这个线程；它从 `mutex_lock` 的睡眠位置恢复后即可返回。队列为空时，解锁才把 `locked` 清零。

## 信号量与条件变量

[`semaphore_down`](https://github.com/LearningOS/uCore-Tutorial-Code-2026A/blob/9d4fa96b67b449bc72f6530286b5a438e9de3ce5/os/sync.c) 先将 `count` 减一。结果小于零，线程便入队睡眠。`semaphore_up` 将 `count` 加一；结果仍小于等于零时，它唤醒一个等待者。被唤醒的线程从原来的 `down` 继续，不再减少一次计数。

`cond_wait` 先释放互斥锁，然后进入条件变量的等待队列；恢复后重新取得互斥锁。`cond_signal` 唤醒队首等待者。若队列为空，本次通知不会留给后来的线程，所以使用者需要在持锁状态下检查共享条件，并在条件不成立时继续等待。

## 资源检查与接口参数

一个进程最多创建 8 个互斥锁、8 个信号量和 8 个条件变量；创建接口按数组位置返回编号，资源用尽时返回 -1。等待队列容量为 16。系统调用在访问对象前检查编号范围。

源码保留了死锁检测的实现位置，但系统调用分发没有启用相应分支。当前互斥锁和信号量按上述等待、唤醒规则运行。

## 运行观察

课程批次以 `ch8b_usertest` 启动，包含 23 项测试。`ch8b_mut_race` 让 15 个工作线程各为共享计数器加 100，最后检查 1500。这一结果可以和阻塞锁的等待队列、解锁时的直接交接对照。

报告中还能沿 `sys_thread_create → allocthread` 看新线程入队，沿 `semaphore_down`、`cond_wait` 查看线程睡眠，再由解锁或通知回到可运行状态。`waittid` 的重复调用体现了“尚未退出就返回 -2”的接口行为，而非内核把调用者放入等待队列。

[查看线程与同步过程](../reports/ucoreos/ch8/2026a/ucore-2026A-ch8-basic-observed.html) · [录制信息](../reports/ucoreos/ch8/2026a/recording.json)
