# rCore 实现

第三章让多个应用同时留在内存中。任务各有用户栈、内核栈和执行上下文；调度器在它们之间切换。源码采用 [2026A 第三章参考实现](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/tree/5deb0f963bf27299a3e8e069b95ea684b781e66e)。

## 任务数组与静态资源

[`TaskManager`](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/blob/5deb0f963bf27299a3e8e069b95ea684b781e66e/os/src/task/mod.rs) 使用固定数组保存任务控制块。应用编号就是数组下标；只有 `0..num_app` 范围内的任务参与调度。每个控制块保存状态、`TaskContext` 和系统调用计数。

应用代码分别装入 `0x80400000 + app_id × 0x20000`。初始化时，任务状态设为 `Ready`，内核栈顶放入初始用户上下文。首次执行该任务时，预设的返回地址指向 `__restore`，从那里恢复寄存器并执行 `sret`。

## 首次运行

`run_first_task` 将任务 0 设为 `Running`，以启动栈上的临时上下文为保存位置，调用 `__switch`。切换汇编保存启动状态后，恢复任务 0 的预设上下文。启动上下文此后不再参加调度。

## 让出与选择下一个任务

`sys_yield` 调用 `suspend_current_and_run_next`，先把当前任务改为 `Ready`。[`run_next_task`](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/blob/5deb0f963bf27299a3e8e069b95ea684b781e66e/os/src/task/mod.rs#L79) 从当前编号的下一项开始循环查找 `Ready` 任务；扫描一圈后也会检查当前任务。

选中其他任务时，调度器取出两个 `TaskContext` 地址，释放对任务管理器的借用，再调用 `__switch`。下一个任务恢复执行后也会访问任务管理器，因此切换时不能保留这次动态借用。

若只有当前任务就绪，它会重新变成 `Running`，`run_next_task` 直接返回。此时没有发生上下文切换，用户的 `yield` 调用仍会正常结束。

## 切换后从哪里继续

[`__switch`](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/blob/5deb0f963bf27299a3e8e069b95ea684b781e66e/os/src/task/switch.S) 保存当前任务的 `ra`、`sp` 和 `s0`—`s11`，再恢复目标任务的相同寄存器。已经运行过的任务，其 `ra` 指向上次调用 `__switch` 之后；恢复后从原来的内核调用链继续，最终返回用户态。

新任务的 `ra` 由初始化代码设为 `__restore`。这使首次运行与后续恢复共用一套切换汇编，而用户态入口由各自的上下文决定。

## 时钟抢占与退出

时钟中断分支先设置下一次触发时间，再调用 `suspend_current_and_run_next`。主动 `yield` 与时钟抢占经过同一条调度路径。

任务退出时，`exit_current_and_run_next` 将状态设为 `Exited`。调度器只选择 `Ready` 任务；所有应用结束后，内核关机。

## 运行观察

报告中一次主动让出的调用链为 `sys_yield → suspend_current_and_run_next → run_next_task → __switch`。这次切换从任务槽位 7 到槽位 8。用户程序输出的 `A`、`B`、`C` 字符行交错出现，对应三个程序轮流运行。

`ch3_sleep` 使用 `get_time()` 和 `yield_()` 等待时间到达。其他任务退出后，它仍不断让出；此时调度器再次选中它自身。函数视图中的 `sys_yield` 次数会继续增加，`__switch` 次数却不会同步增加。

[查看调度报告](../reports/rcore/ch3/2026a/rcore-2026A-ch3-observed.html) · [录制数据](../reports/rcore/ch3/2026a/recording.json)
