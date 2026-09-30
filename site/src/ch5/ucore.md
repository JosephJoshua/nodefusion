# uCore 实现

第五章引入 `fork`、`exec` 和 `wait`，进程不再只能由启动阶段批量装载。下面沿一次“父进程创建子进程、子进程换程序、父进程等待”的过程阅读 [uCore 2026A 第五章源码](https://github.com/LearningOS/uCore-Tutorial-Code-2026A/tree/386f10c55d0285273b78df19c4607c0f475e17a2)。

## 进程与调度器

[`pool`](https://github.com/LearningOS/uCore-Tutorial-Code-2026A/blob/386f10c55d0285273b78df19c4607c0f475e17a2/os/proc.c) 是含 512 个表项的静态进程表。每个表项关联一块静态内核栈和异常上下文页，并记录 PID、状态、页表和父进程。`allocproc` 取得空表项，分配 PID，创建用户页表，初始化首次切入进程所需的内核上下文。

就绪进程的表项下标放入 `task_queue`。调度器从队头取出表项，将进程设为 `RUNNING`，再从 `idle.context` 切入。进程主动让出或被时钟中断抢占时重新排到队尾。

## fork 与地址空间

[`fork`](https://github.com/LearningOS/uCore-Tutorial-Code-2026A/blob/386f10c55d0285273b78df19c4607c0f475e17a2/os/proc.c) 先为子进程创建页表，再用 `uvmcopy` 复制父进程的用户页。每个有效映射对应一块新物理页，内容和权限从父进程复制；原地址空间中的空洞保持为空洞。

子进程还继承用户栈位置、堆边界和异常上下文。内核把子进程保存的 `a0` 改为 0，而父进程从 `fork` 得到新 PID。两者的用户 PC 都已经越过 `ecall`，下一次进入用户态后便从同一调用点的后面分别继续执行。子进程被设为 `RUNNABLE` 并加入队列。

## exec 与程序装载

`exec` 根据名字查找内嵌程序。找到后，先撤销旧程序的低地址用户映射并释放数据页，再由 [`bin_loader`](https://github.com/LearningOS/uCore-Tutorial-Code-2026A/blob/386f10c55d0285273b78df19c4607c0f475e17a2/os/loader.c) 装入新程序。装载器把原始二进制复制到新分配的页，从 `BASE_ADDRESS` 开始映射；代码与栈之间留一页空隙。

这次替换保留 PID、父进程关系、根页表、内核栈和异常上下文的存储。装载器重新设置用户入口、栈和堆边界。`exec` 返回内核异常处理路径后，新程序从新入口开始运行。

## waitpid 与退出

[`wait`](https://github.com/LearningOS/uCore-Tutorial-Code-2026A/blob/386f10c55d0285273b78df19c4607c0f475e17a2/os/proc.c) 在进程表中寻找当前进程的子进程。指定 PID 时只匹配该子进程；`pid <= 0` 匹配任意子进程。子进程仍在运行，父进程就重新入队并切回调度器，下一次获得处理器时继续扫描。

子进程退出时，`freeproc` 解除用户映射、释放数据页和页表页，随后保留一个 `ZOMBIE` 表项供父进程读取退出码。`wait` 找到它后，把表项改为 `UNUSED` 并返回 PID。等待期间，父进程保持 `RUNNABLE`，通过调度器轮换后再次检查。

## 调度策略

[`task_queue`](https://github.com/LearningOS/uCore-Tutorial-Code-2026A/blob/386f10c55d0285273b78df19c4607c0f475e17a2/os/queue.c) 按先进先出顺序保存进程表下标。主动让出、时钟抢占和等待中的父进程都调用 `add_task` 排到队尾；`fetch_task` 由队头取出。

`sched` 只负责把进程上下文切回 `idle.context`。调度器恢复后再取下一项，因此一次进程间轮换会经过两次 `swtch`，中间运行的是调度器。这个实现没有在队列中按优先级排序；`sys_set_priority` 尚未实现。

## 运行观察

课程批次从 `ch5b_usertest` 启动，运行了 fork、退出、等待等 12 项基础测试。第一次 fork 中，PID 1 创建 PID 2；PID 2 执行 `exec` 后退出，父进程在 `wait` 中取得它的退出状态。

在[运行报告](../reports/ucoreos/ch5/2026a/ucore-2026A-ch5-observed.html)中筛选 PID 1 和 PID 2，可以顺着 `fork → exec → exit → wait` 看进程关系；再看 `sched` 与 `swtch`，可见父进程等待期间怎样把处理器交给子进程。[录制信息](../reports/ucoreos/ch5/2026a/recording.json)保存源码版本、运行命令与构建记录。
