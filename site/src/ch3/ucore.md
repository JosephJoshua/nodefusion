# uCore 实现

第三章开始让多个应用共享处理器。内核先把应用分别装入内存，再由调度器决定运行哪一个。以下代码来自 [uCore 2026A 第三章](https://github.com/LearningOS/uCore-Tutorial-Code-2026A/tree/6bb0c2e8d84eda0451092f24f907ed084299e6e)。

## 进程表与上下文

[`proc.c`](https://github.com/LearningOS/uCore-Tutorial-Code-2026A/blob/6bb0c2e8d84eda0451092f24f907ed084299e6e/os/proc.c) 的 `pool` 有 16 个槽。每个槽关联内核栈、用户栈和异常上下文。`allocproc` 取得空槽、分配 PID，将首次运行时的返回地址设为 `usertrapret`，栈指针设为该进程的内核栈顶。

[`run_all_app`](https://github.com/LearningOS/uCore-Tutorial-Code-2026A/blob/6bb0c2e8d84eda0451092f24f907ed084299e6e/os/loader.c) 装入应用、设置用户入口和栈，再把进程设为 `RUNNABLE`。应用依次放在 `0x80400000 + i × 0x20000`。PID 标识进程，调度器扫描的则是 `pool` 槽位；两种编号不能混用。

## 调度器选择进程

`scheduler` 从第一个槽位开始扫描 `pool`。找到 `RUNNABLE` 进程后，它把状态改为 `RUNNING`，更新 `current_proc`，再调用 `swtch(&idle.context, &p->context)`。

`swtch` 保存调度器的寄存器上下文，恢复进程的上下文。第一次切入新进程时，执行从 `usertrapret` 开始，最终通过 `sret` 进入用户态。进程以后再切回调度器，调度器从这次 `swtch` 的下一条指令继续扫描。因此，槽位顺序也决定了一轮扫描中的选择顺序。

## 让出处理器

`yield` 将当前进程改为 `RUNNABLE`，然后调用 `sched`。`sched` 以 `swtch(&p->context, &idle.context)` 保存进程、恢复调度器。调度器随后选择下一进程，再执行一次 `swtch`。即使最后选中的还是原进程，也必须先经过调度器。

用户程序通过系统调用 124 主动让出。时钟中断也调用 `yield`，但会先设置下一次定时器。两条路径会合后，进程都从原来 `sched` 的返回位置继续执行。

这里的 `current_proc` 在调度器恢复后仍指向刚刚离开的进程，直到下一个进程被选中。判断哪段上下文正在执行，应看 `swtch` 的两个参数以及调度器所在的位置。

## 退出与批次结束

`exit` 将进程设为 `UNUSED`，调用 `finished` 记录一个应用完成，再切回调度器。状态已不是 `RUNNABLE`，以后扫描不会选中这个槽。

最后一个应用退出时，`finished` 输出 `all apps over` 并结束运行；这一次不会再执行后面的 `sched`。这与前面各应用正常返回调度器的路径不同。

## 运行观察

九个课程程序同时装入后，三个输出程序的第一轮结果为：

```text
AAAAAAAAAA [1/5]
CCCCCCCCCC [1/5]
BBBBBBBBBB [1/5]
```

每输出一行，程序就主动让出；调度器沿进程表继续寻找下一项。在报告中选择 PID 4 的一次系统调用 124，可以依次看到 `yield → sched → swtch`，随后调度器又以一次 `swtch` 切入 PID 5。前一次保存 PID 4，后一次恢复 PID 5，两次切换都经过 `idle.context`。

时钟中断也走同一条 `yield` 路径。选择 `interrupt.timer`，再查看前后的 `sched.switch`，可以把异常处理、状态改变和两次上下文切换连起来。

[查看调度过程](../reports/ucoreos/ch3/2026a/ucore-2026A-ch3-batch.html) · [录制信息](../reports/ucoreos/ch3/2026a/recording.json)
