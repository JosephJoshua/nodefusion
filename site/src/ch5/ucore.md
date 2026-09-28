# uCore 实现

源码固定到 [`386f10c`](https://github.com/LearningOS/uCore-Tutorial-Code-2026A/tree/386f10c55d0285273b78df19c4607c0f475e17a2) 的 `ch5-api-impl`。进程管理集中在 `os/proc.c`，地址空间管理位于 `os/vm.c`。

## 进程与调度器

[`pool`](https://github.com/LearningOS/uCore-Tutorial-Code-2026A/blob/386f10c55d0285273b78df19c4607c0f475e17a2/os/proc.c) 是包含 512 个 `proc` 的静态数组。每个表项关联静态内核栈和异常上下文页；状态、PID、页表、用户栈和父指针保存在控制块中。

`allocproc` 找到 `UNUSED` 表项，分配单调增加的 PID，将状态设为 `USED`，建立用户页表并初始化上下文。用户页表建立失败时，表项恢复为 `UNUSED`。装载程序后，进程成为 `RUNNABLE`，由调用方加入就绪队列。

调度器从队列头取出进程，将状态改为 `RUNNING`，设置 `current_proc`，从 `idle.context` 切换到进程的上下文。`idle` 使用启动栈，供调度器运行。进程让出处理器时回到队列尾，经过 `sched` 切回调度器。

## fork 与地址空间

[`fork`](https://github.com/LearningOS/uCore-Tutorial-Code-2026A/blob/386f10c55d0285273b78df19c4607c0f475e17a2/os/proc.c) 先调用 `allocproc` 建立子进程，再调用 `uvmcopy` 复制父进程的低地址用户映射。`uvmcopy` 跳过空洞，为每个有效页分配新物理页、复制页内容，并保留原有 PTE 权限。

子进程继承用户栈位置、`max_page` 和堆边界。整个异常上下文复制后，子进程的 `a0` 改为零；`allocproc` 建立的任务上下文仍指向 `usertrapret`，使用子进程自己的静态内核栈。

子进程的父指针指向当前进程。最后将状态设为 `RUNNABLE`，加入队列，向父进程返回新 PID。异常处理器已经移动保存的用户 PC，所以父子进程都从系统调用后的指令继续。

## exec 与程序装载

`sys_exec` 将用户程序名复制到内核缓冲区。`exec` 先按名字查询嵌入程序；找不到时返回 `-1`。查找成功后，`uvmunmap` 清除原有低地址映射并释放数据页，再调用 `loader` 装载目标程序。

[`bin_loader`](https://github.com/LearningOS/uCore-Tutorial-Code-2026A/blob/386f10c55d0285273b78df19c4607c0f475e17a2/os/loader.c) 将原始二进制复制到独立物理页，映射到 `BASE_ADDRESS` 起始的用户地址，装载区使用 `RWXU`。用户栈使用新的读写页，代码与栈之间留出一页空隙。装载结束后设置入口 PC、用户栈顶、`max_page` 和堆边界。

现有 PID、父指针、内核栈、异常上下文存储和根页表保留。共享跳板与异常上下文的特殊映射也保留。装载器将状态写为 `RUNNABLE`，当前内核调用继续执行并返回用户态，这条路径没有再次向队列插入进程。

本章 `sys_spawn` 和 `sys_set_priority` 的函数体返回 `-1`，系统调用分发中没有设置优先级的分支。对应代码位置可以与 rCore 的直接创建和 stride 调度实现对照阅读。

## waitpid 与退出

[`wait`](https://github.com/LearningOS/uCore-Tutorial-Code-2026A/blob/386f10c55d0285273b78df19c4607c0f475e17a2/os/proc.c) 扫描进程表，寻找父指针等于当前进程的表项。`pid <= 0` 匹配任意子进程，正 PID 匹配指定子进程。

找到僵尸进程时，`wait` 将其状态设为 `UNUSED`，写出退出码并返回 PID。没有匹配的子进程时返回 `-1`。匹配的子进程尚未退出时，父进程设为 `RUNNABLE`，重新入队并调用 `sched`；下次被调度后从扫描循环继续。这个等待路径使用就绪状态，未使用 `SLEEPING` 状态。

`exit` 保存退出码，调用 `freeproc`。后者移除跳板和异常上下文的特殊映射，再释放低地址用户页和各级页表页。特殊映射使用 `do_free = 0`，其物理存储由内核静态资源持有。

有父进程的表项随后设为 `ZOMBIE`，保留等待所需的信息。退出进程的所有子进程清空父指针；其中已为 `ZOMBIE` 的表项立即恢复为 `UNUSED`。仍在运行的孤儿进程继续执行，退出时直接释放表项。

因此，成功的 `wait` 主要回收进程表项。内核栈和异常上下文数组一直存在，下次分配这个表项时重新初始化。

## 调度策略

[`task_queue`](https://github.com/LearningOS/uCore-Tutorial-Code-2026A/blob/386f10c55d0285273b78df19c4607c0f475e17a2/os/queue.c) 使用进程表下标保存就绪队列。`fetch_task` 从队头取出下标，`add_task` 向队尾插入。主动让出、时钟抢占和等待未退出子进程都通过这条队列轮换。

`sched` 检查当前进程已经离开 `RUNNING` 状态，再保存进程上下文并恢复 idle 上下文。这里不选择下一个进程；选择发生在调度器恢复后的循环中。

队列为空时，调度器通过 `all app are over!` 的 panic 路径结束批次。普通用户测试的退出码与这个内核结束提示分别由用户程序和调度器产生。

## 运行观察

本次以 `ch5b_usertest` 为初始进程，运行输出、睡眠、让出处理器、PID、fork 和退出等 12 项基础测试。它们都以零退出，课程检查通过。观察版内核内嵌的 16 份用户二进制与参考构建逐一相同。

| 观察点 | 完整轨迹统计 |
| --- | ---: |
| fork 成功 | 60 |
| `exec` 入口 | 17 |
| `wait` 入口 | 65 |
| `allocproc` 入口 | 61 |
| `uvmunmap` 入口 | 200 |
| 物理页分配 | 606 |
| 物理页归还 | 539 |
| 分配器使用页数峰值 | 123 |
| 录制结束时分配器使用页数 | 67 |

第一次 fork 位于指令计数 `413,158,400`，由 PID 1 创建 PID 2。PID 2 在 `413,161,954` 进入 `exec`，在 `413,316,173` 进入 `exit`，退出码为零。PID 1 的 `wait` 入口位于 `413,158,902`，此时子进程尚未退出。沿这个等待过程，可以查看父进程如何重新入队，子进程如何获得处理器，以及等待循环从哪里恢复。

这份完整轨迹记录 512,674 次上下文切换，与 `swtch` 的入口次数相同。其中 256,337 次从 idle 到进程，另外 256,337 次从进程回到 idle。等待和让出处理器会多次经过这条路径；一次切换记录对应一次上下文切换，进程之间的轮换经过 idle 上下文。

物理页分配器每次操作后都满足空闲页数与使用页数之和为 31,131。606 次分配减去 539 次归还，得到录制结束时的 67 页。这个计数从分配器初始化后开始，与内核镜像和静态数组预留的物理存储分别计量。

[打开基础测试报告](../reports/ucoreos/ch5/2026a/ucore-2026A-ch5-observed.html)。事件视图按 PID 1、2 筛选，可以跟随第一次创建与等待；函数视图搜索 `wait`、`sched`、`swtch` 和 `freeproc`，查看等待与资源释放的调用关系。报告保留 150,000 条浏览样本，上表使用完整轨迹统计。

<details>
<summary>构建与录制参数</summary>

用户程序固定到 [`1733f46`](https://github.com/LearningOS/uCore-Tutorial-Test/tree/1733f460c596b013b1c509ad42afa428640783b0)。构建先应用 `ucore-2026a-build.patch` 和 `ucore-2026a-ch5-observation.patch`。前者修正汇编源文件列表，后者加入物理页、fork 和调度切换的语义记录。

GCC 为 14.2.0，CMake 为 3.31.6，QEMU 为 10.2.2。内核构建命令为 `make build LOG=info CHAPTER=5 INIT_PROC=ch5b_usertest`。构建时重新嵌入参考版本的 16 份用户二进制，再执行普通 QEMU 和课程检查。

录制覆盖启动到批次结束，使用 `--no-build --function-returns --watch-all --profile uniform --snapshots 80 --max-ram-bytes 268435456 --timeout 180 --no-render --event-stream never`。

[录制记录](../reports/ucoreos/ch5/2026a/recording.json)保存完整命令、工具版本、补丁、内嵌用户程序与校验值。报告从同一份轨迹重新分析，录制来源与分析来源分别保存。调度器结束批次的提示按课程运行结果检查。

</details>
