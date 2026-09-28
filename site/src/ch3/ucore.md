# uCore 实现

本节分析课程仓库 `ch3-api-impl` 的提交 [`6bb0c2e`](https://github.com/LearningOS/uCore-Tutorial-Code-2026A/tree/6bb0c2e8d84eda0451092f24f907ed084299e6e6)。调度代码位于 [`os/proc.c`](https://github.com/LearningOS/uCore-Tutorial-Code-2026A/blob/6bb0c2e8d84eda0451092f24f907ed084299e6e6/os/proc.c)。本章源码将静态加载的执行实体称为进程。

## 进程表与上下文

`pool` 是容量为 16 的进程表。每个槽位对应静态分配的内核栈、用户栈和陷阱帧。`proc_init` 建立这些指针关系，清零系统调用计数，并将槽位设为 `UNUSED`。

`idle` 保存启动阶段和调度器的上下文。启动时 `current_proc` 指向 `idle`。进程获得处理器前，调度器将 `current_proc` 更新为该进程。

[`allocproc`](https://github.com/LearningOS/uCore-Tutorial-Code-2026A/blob/6bb0c2e8d84eda0451092f24f907ed084299e6e6/os/proc.c#L60) 从空闲槽位中分配进程。它设置 PID，将状态改为 `USED`，清零陷阱帧与内核栈，并把初始 `context.ra` 设为 `usertrapret`、`context.sp` 设为内核栈顶。

[`run_all_app`](https://github.com/LearningOS/uCore-Tutorial-Code-2026A/blob/6bb0c2e8d84eda0451092f24f907ed084299e6e6/os/loader.c) 完成应用装载，为陷阱帧设置用户入口与用户栈，再把进程改为 `RUNNABLE`。应用装载地址为 `0x80400000 + i × 0x20000`。

PID 与数组下标用途不同。调度器按槽位扫描，运行报告中的进程标识则需要结合 PID 阅读。

## 调度器选择进程

[`scheduler`](https://github.com/LearningOS/uCore-Tutorial-Code-2026A/blob/6bb0c2e8d84eda0451092f24f907ed084299e6e6/os/proc.c#L92) 在无限循环中扫描 `pool`：

```c
for (p = pool; p < &pool[NPROC]; p++) {
    if (p->state == RUNNABLE) {
        p->state = RUNNING;
        current_proc = p;
        swtch(&idle.context, &p->context);
    }
}
```

选中进程时，`swtch` 保存调度器上下文并恢复进程上下文。进程后来返回调度器时，执行继续到这次 `swtch` 之后，`for` 循环检查后面的槽位。扫描到数组末尾后，再从第一个槽位开始。

首次选中的进程恢复到 `usertrapret`。该函数依据陷阱帧设置返回用户态所需的寄存器，并调用 `userret`；返回汇编恢复用户寄存器后执行 `sret`。

## 让出处理器

[`yield`](https://github.com/LearningOS/uCore-Tutorial-Code-2026A/blob/6bb0c2e8d84eda0451092f24f907ed084299e6e6/os/proc.c#L128) 将当前进程改为 `RUNNABLE`，随后调用 `sched`。`sched` 检查进程已经离开 `RUNNING` 状态，再执行：

```c
swtch(&p->context, &idle.context);
```

本次切换保存进程上下文，恢复调度器的继续执行位置。调度器随后选择下一进程，并进行第二次切换。即使只有当前进程可运行，这条路径仍然经过调度器，再恢复同一进程。

再次选中原进程时，执行从它原来的 `swtch` 调用之后继续，依次返回 `sched`、`yield` 和调用它的处理函数。主动让出由 `sys_sched_yield` 调用；时钟中断则在 `usertrap` 中设置下一次定时器后调用 `yield`。

`scheduler` 返回后的扫描阶段没有把 `current_proc` 改回 `idle`。此时这个指针仍指向上一进程。因此，观察调度器阶段时，需要结合切换参数和所处代码判断实际上下文。

## 退出与批次结束

[`exit`](https://github.com/LearningOS/uCore-Tutorial-Code-2026A/blob/6bb0c2e8d84eda0451092f24f907ed084299e6e6/os/proc.c#L143) 把进程设为 `UNUSED`，调用 `finished` 记录一个应用完成，然后返回调度器。该进程不再符合 `RUNNABLE` 条件。

最后一个应用退出时，`finished` 输出 `all apps over` 并通过内核的 panic 路径结束批次。此时退出流程在 `finished` 内终止，后面的 `sched` 没有执行。阅读最后一次退出的轨迹时，应与普通退出区分。

## 运行观察

本次运行加载九个课程测试程序。PID 按装载顺序从 1 到 9 分配，进程表槽位从 0 到 8 使用。三个输出程序的一轮输出如下：

```text
AAAAAAAAAA [1/5]
CCCCCCCCCC [1/5]
BBBBBBBBBB [1/5]
```

每个程序输出一行后主动让出处理器。调度器继续扫描下一个槽位，形成交错输出。

在第 17,511,329 条指令处，PID 4 的 `ch3_trace` 执行系统调用 124。沿随后记录的函数入口，可以找到两次切换：

| 指令计数 | 入口或动作 | 执行过程 |
| --- | --- | --- |
| 17,511,329 | `ecall`，系统调用 124 | PID 4 请求让出 |
| 17,511,415 | `syscall` | 分发系统调用 |
| 17,511,489 | `yield` | 将 PID 4 改为 `RUNNABLE` |
| 17,511,499 | `sched` | 准备返回调度器 |
| 17,511,514 | `swtch` | 保存 PID 4，恢复 `idle.context` |
| 17,511,554 | `swtch` | 保存调度器，恢复 PID 5 |

两次 `swtch` 的中间参数都指向 `idle.context`。PID 4 的上下文地址对应槽位 3，PID 5 对应槽位 4，下一进程的选择与源码中的扫描顺序一致。

时钟抢占也经过同一条 `yield` 路径。首次记录的时钟中断位于第 15,946,665 条指令，随后依次进入 `yield`、`sched`，再从 PID 1 切回调度器并运行 PID 2。

完整轨迹中的计数如下。主动让出次数按用户态 `ecall` 的系统调用号统计，函数次数按入口事件统计。

| 观察点 | 次数 |
| --- | ---: |
| 主动让出，系统调用 124 | 583,445 |
| 时钟中断 | 301 |
| `yield` | 583,746 |
| `sched` | 583,754 |
| `swtch` | 1,167,509 |
| `exit` | 9 |

583,445 次主动让出与 301 次时钟中断共调用 `yield` 583,746 次。八次普通退出又调用 `sched`，因此 `sched` 总计 583,754 次。每次返回调度器后都有一次恢复进程的切换，加上首次启动，`swtch` 的次数为 `2 × 583,754 + 1`。

最后一个结束的程序是 PID 5 的 `ch3b_sleep`。它通过查询时间并反复让出来等待时间到达。其他程序结束后，它仍然先返回调度器，再恢复自身。最后一次退出把槽位改为 `UNUSED`，随后在 `finished` 中结束运行；最后一份快照中已没有活跃进程。

[打开本次运行报告](../reports/ucoreos/ch3/2026a/ucore-2026A-ch3-batch.html)，在事件浏览器筛选 `sched.switch`，比较 `old_ctx`、`new_ctx` 与切入、切出 PID。再选择 `interrupt.timer`，沿相邻事件查看抢占过程。交互报告保留 150,000 条事件，以上计数来自完整轨迹。

<details>
<summary>构建与录制参数</summary>

课程构建检查 `python tools/run_lab.py --mode positive` 通过。构建使用 GCC 14.2.0、CMake 3.31.6 与 QEMU 10.2.2。应用课程提供的测试兼容补丁，并将 Makefile 的汇编源文件列表改为即时展开，避免生成 `link_app.S` 后重复收集对应目标文件。

```sh
python -m nodefusion.host.cli record \
  --kernel /home/joseph/nf/education-2026A-20260927/ucore-ch3 \
  --kernel-kind ucore \
  --runs /home/joseph/nf/education-2026A-20260927/runs \
  --name ucore-2026A-ch3-batch --no-build \
  --function-returns --watch-all --profile uniform --snapshots 160 \
  --max-ram-bytes 268435456 --timeout 120 --no-render --event-stream never
```

原始轨迹为 16,344,247 条事件，内核 ELF 校验和为 `3205969f8416b9a8ca106a1dfc8f610df8ced0906c354cf38ceeaf210a988224`。完整命令、源版本、补丁和数据校验和见 [recording.json](../reports/ucoreos/ch3/2026a/recording.json)。

</details>

## 源码阅读练习

1. 一个进程返回调度器后，为什么下一次扫描从它后面的槽位继续？保存的 `ra` 指向什么位置？
2. `yield` 与 `exit` 分别把状态改为什么？这些状态如何影响调度？
3. 调度器正在扫描时，`current_proc` 指向谁？单凭这个指针能否判断当前执行的是哪个上下文？
4. 最后一个应用退出时，为什么没有从进程切回调度器？
