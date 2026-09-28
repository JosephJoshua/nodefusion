# rCore 实现

本节分析课程仓库 `ch3-api-impl` 的提交 [`5deb0f9`](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/tree/5deb0f963bf27299a3e8e069b95ea684b781e66e)。任务管理代码位于 [`os/src/task/mod.rs`](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/blob/5deb0f963bf27299a3e8e069b95ea684b781e66e/os/src/task/mod.rs)。

## 任务数组与静态资源

`TaskManager` 保存实际应用数量 `num_app`。`TaskManagerInner` 保存任务控制块数组和当前任务编号 `current_task`。本章任务编号等于数组下标；数组容量为 16，只有 `0..num_app` 参与调度。

每个控制块包含任务状态、`TaskContext` 和独立的系统调用计数数组。用户栈与内核栈由 [`loader.rs`](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/blob/5deb0f963bf27299a3e8e069b95ea684b781e66e/os/src/loader.rs) 中的静态数组提供。应用代码装载到 `0x80400000 + app_id × 0x20000`。

`TASK_MANAGER` 首次被访问时初始化。有效任务设为 `Ready`，其余槽位保持 `UnInit`。`init_app_cx` 在各任务的内核栈顶放置初始用户上下文；`TaskContext::goto_restore` 将 `ra` 设为 `__restore`，将 `sp` 设为该上下文的地址。

因此，第一次恢复一个任务时，切换汇编直接进入异常返回代码。初始用户上下文中已经准备好应用入口和用户栈指针。

## 首次运行

[`run_first_task`](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/blob/5deb0f963bf27299a3e8e069b95ea684b781e66e/os/src/task/mod.rs#L133) 把任务 0 设为 `Running`，取得其上下文指针，然后释放 `inner` 的借用。函数在启动栈上准备 `boot_task_cx`，将启动上下文保存到这里，并恢复任务 0。

启动上下文随后不再参与调度。任务首次进入 `__restore`，恢复用户寄存器，再执行 `sret`。

## 让出与选择下一个任务

[`suspend_current_and_run_next`](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/blob/5deb0f963bf27299a3e8e069b95ea684b781e66e/os/src/task/mod.rs#L156) 先把当前任务改为 `Ready`，随后调用 `run_next_task`。选择过程为：

```rust,ignore
let next = (1..=self.num_app)
    .map(|offset| (current + offset) % self.num_app)
    .find(|&task_id| inner.tasks[task_id].task_status == TaskStatus::Ready);
```

扫描从当前任务的下一个编号开始，绕过数组末尾，最后检查当前任务自身。选中目标后，更新目标状态与 `current_task`，再取得两个上下文指针。

当目标就是当前任务时，函数直接返回。此前的 `Ready` 已改回 `Running`，应用可以继续执行。这一情况发生在其他任务都没有就绪时，没有执行 `__switch`。

目标为其他任务时，`drop(inner)` 释放动态借用，再执行 `__switch`。下一任务可能立即进入任务管理代码，因此该借用必须在切换前结束。上下文指针仍然有效，因为它们指向全局任务数组。

## 切换后从哪里继续

[`switch.S`](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/blob/5deb0f963bf27299a3e8e069b95ea684b781e66e/os/src/task/switch.S) 将当前 `ra`、`sp` 和 `s0`—`s11` 写入 `a0` 指向的上下文，再从 `a1` 指向的上下文恢复这些寄存器。

对已经运行过的任务，保存的 `ra` 指向原 `__switch` 调用之后。再次选中这个任务时，执行流回到 `run_next_task`，再逐层返回调度入口和异常处理函数，最终恢复用户态。因此，应用看到的效果是让出调用结束，循环继续。

首次运行的任务使用初始化时设置的 `ra = __restore`，直接完成用户态恢复。

## 时钟抢占与退出

[`trap_handler`](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/blob/5deb0f963bf27299a3e8e069b95ea684b781e66e/os/src/trap/mod.rs) 在时钟中断分支先调用 `set_next_trigger`，再调用同一个暂停接口。用户调用 `sys_yield` 时也进入该接口。

[`exit_current_and_run_next`](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/blob/5deb0f963bf27299a3e8e069b95ea684b781e66e/os/src/task/mod.rs#L171) 将任务设为 `Exited` 后选择下一任务。已经退出的任务不符合 `Ready` 条件，不再被恢复。当没有就绪任务时，内核输出完成信息并关机。

## 运行观察

本次运行选择用户测试仓库中的第二、三章程序，共 13 个应用。`ch2b_bad_address`、`ch2b_bad_instructions` 和 `ch2b_bad_register` 分别触发访问异常或非法指令，内核结束对应任务后继续运行其他应用。

三个让出处理器的程序各输出五行字符，再报告完成。串口输出中的一段为：

```text
AAAAAAAAAA [1/5]
BBBBBBBBBB [1/5]
CCCCCCCCCC [1/5]
```

每个程序在输出一行后调用 `yield_()`。计算任务和等待时间的程序也参与调度，因此后续字符行之间会夹有其他输出。

第一次主动让出的轨迹包含以下四个入口。指令数为从虚拟机启动开始累计执行的指令数量：

| 累计指令数 | 入口 | 作用 |
| ---: | --- | --- |
| 22,558,198 | `sys_yield` | 接收用户让出请求 |
| 22,558,205 | `suspend_current_and_run_next` | 将当前任务设为就绪 |
| 22,558,249 | `run_next_task` | 选择下一个就绪任务 |
| 22,558,307 | `__switch` | 从槽位 7 切换到槽位 8 |

切换参数中的两个上下文地址分别属于槽位 7 和 8。此次执行的是等待时间的 `ch3_sleep`，随后恢复 `ch3_sleep1`。另一个片段从第 19,356,419 条指令处的时钟中断开始，也依次进入暂停、选择和切换入口，最终从槽位 4 切换到槽位 5。

完整轨迹中的入口计数如下：

| 观察点 | 次数 |
| --- | ---: |
| `sys_yield` | 798,474 |
| 时钟中断 | 302 |
| `suspend_current_and_run_next` | 798,776 |
| `exit_current_and_run_next` | 13 |
| `run_next_task` | 798,789 |
| `__switch` | 125,644 |

暂停次数等于主动让出次数与时钟中断次数之和。暂停和退出都调用 `run_next_task`，两者相加正好得到其入口次数。

`__switch` 包含一次首次启动，剩余 125,643 次由 `run_next_task` 调用。再扣除最后一次没有就绪任务的关机路径，可由源码和计数推算：673,145 次调度选择了当前任务自身，直接返回。

`ch3_sleep` 使用 `get_time()` 与 `yield_()` 循环等待时间到达。其他应用结束后，它仍然反复请求调度。此时任务表只有一个 `Running` 和十二个 `Exited`，另外三个槽位保持 `UnInit`。结合自选返回分支，可以解释大量让出调用为何没有执行切换汇编。

[打开本次运行报告](../reports/rcore/ch3/2026a/rcore-2026A-ch3-observed.html)。在事件浏览器中选择 `sched.yield`、`sched.switch` 或 `interrupt.timer`，再结合任务状态查看。计数使用完整轨迹；交互报告保留 150,000 条事件供浏览。

<details>
<summary>构建与录制参数</summary>

内核提交为 `5deb0f963bf27299a3e8e069b95ea684b781e66e`，用户程序提交为 `a0593662ad55d670ba8c27ce1763347cd0dd552f`。Rust 工具链为 `nightly-2024-05-02`，QEMU 为 10.2.2，NodeFusion 提交为 `bce9de05d36d5cdd0afc71121e7c9b1016c08664`。

录制前应用 `rcore-2026a-ch3-observation.patch`，为暂停函数添加 `#[inline(never)]`，保留独立函数入口。录制命令为：

```sh
python -m nodefusion.host.cli record \
  --kernel /home/joseph/nf/education-2026A-20260927/rcore-ch3 \
  --kernel-kind rcore \
  --runs /home/joseph/nf/education-2026A-20260927/runs \
  --name rcore-2026A-ch3-observed \
  --make-var CHAPTER=3 --make-var TEST=3 \
  --make-var BASE=2 --make-var OFFLINE=1 \
  --function-returns --watch-all --profile uniform --snapshots 160 \
  --max-ram-bytes 268435456 --timeout 120 \
  --no-render --event-stream never
```

输出包含 8,115,353 条事件、172 份快照。原始轨迹的 SHA-256 为 `ce22cb967ff87bf17360acfddea10da2506cb376f7829ae845c3b2a7cd448bed`，内核 ELF 的 SHA-256 为 `e9198f5612c8cc6085e0ee659800a0298a762b023950e7472c1ccc7b45b10298`。输入与报告校验值见[运行数据](../reports/rcore/ch3/2026a/recording.json)。

</details>

## 源码阅读练习

1. 假设三个任务的状态依次为 `Exited`、`Running`、`Ready`，当前编号为 1。任务 1 让出后，扫描依次检查哪些编号？
2. 只剩任务 1 时，一次 `sys_yield` 会改变哪些状态？是否保存切换上下文？
3. 如果删除 `drop(inner)`，下一任务访问任务管理器时会发生什么？结合 `UPSafeCell` 的实现解释。
4. 分别指出首次运行与暂停后恢复使用的 `ra` 来源。
