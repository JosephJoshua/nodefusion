# rCore 实现

第八章将进程内的执行流拆分为线程，并提供互斥锁、信号量和条件变量。线程共享地址空间，各自保存栈与执行上下文。源码采用 [2026A 第八章参考实现](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/tree/00b2a84360710640fbde595c194a7f2447e755f2)。

## 进程与线程

[`ProcessControlBlock`](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/blob/00b2a84360710640fbde595c194a7f2447e755f2/os/src/task/process.rs) 持有地址空间、文件描述符表、线程列表和同步对象。[`TaskControlBlock`](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/blob/00b2a84360710640fbde595c194a7f2447e755f2/os/src/task/task.rs) 保存单个线程的内核栈、任务上下文、状态、退出码及用户资源。

每个线程有自己的用户栈和异常上下文页。用户栈大小为 8 KiB，相邻栈之间留 4 KiB 空隙。同一进程的线程使用同一张用户页表，因此可以访问相同的全局变量和堆数据。

## 创建、退出与等待

[`sys_thread_create`](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/blob/00b2a84360710640fbde595c194a7f2447e755f2/os/src/syscall/thread.rs) 分配 TID 与线程资源，设置新线程的入口、用户栈和 `a0` 参数，再把线程加入就绪队列。返回值是进程内的线程编号。

线程退出时，内核释放它的用户栈和异常上下文页，记录退出码。`waittid` 查询线程状态：自身或空槽返回 `-1`，尚未退出返回 `-2`，已退出则取走线程槽并返回退出码。TID 的回收发生在用户资源释放时，分析连续创建的线程时需要同时看创建顺序和控制块。

## 调度、阻塞与唤醒

就绪队列按 FIFO 取线程。主动让出时，当前线程回到就绪队列；等待同步对象时，`block_current_and_run_next` 将它设为 `Blocked`，调度器暂时不再选择它。同步对象调用 `wakeup_task` 后，线程重新进入就绪队列。

上下文切换经过处理器的空闲上下文：先保存当前线程，再选择下一个线程恢复。函数调用报告中的一次阻塞和唤醒，可以沿线程对象、进程 PID 及两段切换记录连接起来。

## 互斥锁

[`MutexSpin`](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/blob/00b2a84360710640fbde595c194a7f2447e755f2/os/src/sync/mutex.rs) 遇到已占用的锁时调用 `suspend_current_and_run_next`，恢复运行后再次检查锁。等待者仍是就绪线程。

`MutexBlocking` 则把等待者放入 FIFO 队列并阻塞。解锁时若队列非空，内核将锁交给队首线程并唤醒它；`locked` 仍为 `true`。被唤醒的线程从原来的 `lock` 调用继续，无需再次竞争。没有等待者时，解锁才把 `locked` 清为 `false`。

## 信号量与条件变量

[`Semaphore`](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/blob/00b2a84360710640fbde595c194a7f2447e755f2/os/src/sync/semaphore.rs) 使用有符号的 `count`。`down` 先减一；结果小于零时，线程进入等待队列并阻塞。`up` 加一；结果仍小于等于零时，把许可交给队首线程并唤醒它。负数的绝对值对应队列中等待的线程数。

[`Condvar::wait`](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/blob/00b2a84360710640fbde595c194a7f2447e755f2/os/src/sync/condvar.rs) 释放调用者持有的互斥锁，将当前线程加入条件变量队列，然后阻塞。`signal` 唤醒队首线程；线程恢复后先重新取得互斥锁，`wait` 才返回。用户程序用循环检查共享条件，因为再次取得锁时条件可能已经改变。

## 资源检查与接口参数

进程分别为互斥锁和信号量维护一个 [`DeadlockDetector`](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/blob/00b2a84360710640fbde595c194a7f2447e755f2/os/src/sync/deadlock.rs)。它记录当前可用的资源、各线程已持有的资源，以及正在等待的一个资源。

`is_safe` 用一份可用资源副本模拟：找到当前请求可以得到满足的线程，把该线程已持有的资源归还到副本中，再寻找下一个。若所有线程都能依次完成，请求通过；否则，启用检查的系统调用返回 `-0xDEAD`，不会把这次请求加入同步对象的计数或队列。

## 运行观察

基础测试中的 `ch8b_race_adder_mutex_spin` 创建 16 个工作线程，每个线程完成 1000 次共享计数器更新。沿 `MutexSpin::lock → MutexSpin::unlock` 查看临界区，可将最终结果 16000 与更新次数对应起来。

条件变量测试中，等待线程从 `Condvar::wait` 阻塞，通知线程调用 `signal`，等待线程被唤醒后再次取得互斥锁。扩展报告还运行互斥锁、信号量的资源检查用例；沿 `sys_enable_deadlock_detect` 与 `is_safe` 可查看检查何时开启、何时判断请求。

[基础测试报告](../reports/rcore/ch8/2026a/rcore-2026A-ch8-basic-observed-v3.html) · [扩展测试报告](../reports/rcore/ch8/2026a/rcore-2026A-ch8-extended-observed-v3.html) · [录制数据](../reports/rcore/ch8/2026a/recording.json)
