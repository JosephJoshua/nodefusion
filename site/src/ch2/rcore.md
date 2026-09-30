# rCore 实现

第二章把多个应用依次装入同一段内存。应用通过系统调用请求输出或退出；发生异常时，内核结束当前应用并运行下一个。源码采用 [2026A 第二章参考实现](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/tree/529d8bafef3dea5489c85a565d912307f6bbccb7)。

## 批次状态与装载

[`AppManager`](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/blob/529d8bafef3dea5489c85a565d912307f6bbccb7/os/src/batch.rs) 保存应用数量、下一应用序号和各应用的起始地址。地址表比应用数多一项；相邻地址确定一个应用二进制的范围。

`run_next_app` 读取 `current_app`，调用 `load_app`，再把序号加一。`load_app` 清空从 `0x80400000` 开始的 128 KiB 区域，将应用复制进去，并执行 `fence.i`。应用代码刚由数据写入指令内存，执行 `fence.i` 后，处理器取指才会看到新内容。

管理器保存的是下一次要装载的序号。应用 0 正在运行时，`current_app` 已经是 1。所有应用执行完毕后，最后一次 `run_next_app` 通过 QEMU 退出设备关机。

## 首次进入用户态

[`TrapContext::app_init_context`](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/blob/529d8bafef3dea5489c85a565d912307f6bbccb7/os/src/trap/context.rs) 准备应用入口 `0x80400000`、用户栈顶和返回用户态所需的 `sstatus`。`run_next_app` 把这份上下文放在内核栈上，随后直接进入 `__restore`。第一次进入用户态也沿用异常返回的汇编路径。

## 异常入口与上下文

用户态发生异常后，[`__alltraps`](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/blob/529d8bafef3dea5489c85a565d912307f6bbccb7/os/src/trap/trap.S) 交换 `sp` 与 `sscratch`，切到内核栈。汇编在栈上保存用户寄存器、`sstatus` 和 `sepc`，把得到的 `TrapContext` 地址交给 `trap_handler`。

返回路径由 `__restore` 从同一份上下文恢复寄存器，最后执行 `sret`。用户栈指针保存在上下文的 `x[2]` 中；处理异常期间的函数调用使用内核栈。

## 系统调用与返回

用户程序执行 `ecall` 时，[`trap_handler`](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/blob/529d8bafef3dea5489c85a565d912307f6bbccb7/os/src/trap/mod.rs) 从 `a7` 读取调用号，从 `a0`—`a2` 读取参数，并把返回值写回上下文的 `a0`。处理前先将 `sepc` 加 4，返回用户态后便从 `ecall` 的下一条指令继续。

本章的 `sys_write` 接收标准输出描述符 1，将给定缓冲区作为 UTF-8 文本输出，返回写入长度。`sys_exit` 不再返回当前应用，而是调用 `run_next_app` 装载下一项。

## 退出与应用异常

写地址零、执行无效指令等应用错误由异常处理器识别。`StoreFault`、`StorePageFault` 和 `IllegalInstruction` 会结束当前应用并运行下一项；内核不再恢复出错的上下文。第二章的七个应用中有三个故意触发异常，其余四个通过 `exit` 结束。

## 运行观察

报告中的第一条 `write` 先进入 `trap_handler`，随后沿 `syscall → sys_write` 输出文本。继续查看 `run_next_app`，可以看到每次退出或应用异常后，下一份应用二进制被装入同一地址。七个应用结束后，内核输出 `All applications completed!`。

[查看函数调用报告](../reports/rcore/ch2/2026a/rcore-2026A-ch2-reference.html) · [录制数据](../reports/rcore/ch2/2026a/rcore-2026A-ch2-reference.json)
