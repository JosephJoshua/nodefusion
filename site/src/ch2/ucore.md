# uCore 实现

第二章的内核每次只运行一个用户程序。程序退出或发生异常后，内核装入下一个程序。这里使用 [uCore 2026A 第二章源码](https://github.com/LearningOS/uCore-Tutorial-Code-2026A/tree/729e1ad1632bb639dfe546f34765c0537b503990)。

## 批次状态与装载

[`loader.c`](https://github.com/LearningOS/uCore-Tutorial-Code-2026A/blob/729e1ad1632bb639dfe546f34765c0537b503990/os/loader.c) 用 `app_num` 记录应用数，`app_cur` 记录当前应用的序号。初值 -1 让第一次 `run_next_app` 将它推进到 0。应用的位置保存在内核映像中的地址表里；`run_next_app` 每次推进表指针，再调用 `load_app`。

`load_app` 先清零从 `0x80400000` 开始的 `0x20000` 字节，再把应用复制到这块固定的执行区域。随后内核清零 `trap_page`，为新应用设置入口地址和用户栈。其余应用仍在内核映像中等待装载。

## 首次进入用户态

`user_stack` 和 `trap_page` 各占一页。`run_next_app` 将 `trap_page` 解释为 `struct trapframe`，写入用户入口 `0x80400000` 和用户栈顶，再调用 [`usertrapret`](https://github.com/LearningOS/uCore-Tutorial-Code-2026A/blob/729e1ad1632bb639dfe546f34765c0537b503990/os/trap.c)。

`usertrapret` 准备 `sepc`、`sstatus` 和下次进入内核所需的栈地址，随后由 `userret` 恢复用户寄存器。最终的 `sret` 将处理器切换到用户态，从 `sepc` 开始执行应用。

## 异常入口与上下文

[`uservec`](https://github.com/LearningOS/uCore-Tutorial-Code-2026A/blob/729e1ad1632bb639dfe546f34765c0537b503990/os/trampoline.S) 先用 `sscratch` 取得 `trapframe` 地址，再保存用户寄存器和 `sepc`。原来的用户 `a0` 也写入 `trapframe`，随后入口读取 `kernel_sp`、`kernel_trap` 等字段，切换到内核栈并调用 `usertrap`。

返回时，`userret` 从同一份 `trapframe` 恢复寄存器，再执行 `sret`。本章尚未启用分页：汇编中切换 `satp` 和执行 `sfence.vma` 的代码被注释。

## 系统调用与返回

用户程序执行 `ecall` 后，`usertrap` 把保存的 `epc` 增加 4，使返回地址越过这条指令。[`syscall`](https://github.com/LearningOS/uCore-Tutorial-Code-2026A/blob/729e1ad1632bb639dfe546f34765c0537b503990/os/syscall.c) 从 `trap_page` 读取 `a7` 中的调用号和参数，把返回值写回保存的 `a0`。

`sys_write` 只接受描述符 1，逐字节输出后返回长度；其他描述符和未知调用号返回 -1。这个版本尚无用户页表，缓冲区地址也没有经过地址空间检查。

## 退出与应用异常

`sys_exit` 调用 `run_next_app`，把执行区域交给下一个应用。若批次结束，则输出 `ALL DONE` 并关机。非法指令、未对齐访问和页异常也会进入异常处理路径；报告异常后，内核继续装载下一应用。源码中的 `core dumped.` 只是诊断文字。

## 栈地址与上下文页

参考实现给 `usertrapret` 传入 `boot_stack_top`，函数内部又计算：

```c
trapframe->kernel_sp = kstack + PGSIZE;
```

这次构建的 `boot_stack_top` 为 `0x80219000`，而 `trap_page` 正好占据 `[0x80219000, 0x8021a000)`。因此异常入口使用的栈顶是 `0x8021a000`；栈向低地址增长，处理函数实际在 `trap_page` 内使用栈。第一个应用退出后，`run_next_app` 清零这整页，也覆盖了当前调用栈上的返回地址。

独立修正构建将赋值改为 `trapframe->kernel_sp = kstack;`。处理函数回到启动栈，三个普通应用依次退出，退出码为 1234、0、0。这个问题可以用 `sp`、`trap_page` 边界和 `memset` 的目标地址直接定位。

## 运行观察

| 运行 | 结果 | `usertrap` 次数 |
| --- | --- | ---: |
| 原参考构建，三个普通应用 | 第一个应用退出后停滞 | 1 |
| 栈地址修正版，同一批次 | 三个应用结束 | 16 |
| 栈地址修正版，三个异常应用 | 三次异常后结束批次 | 3 |

普通批次的 16 次异常都是系统调用，包括 13 次 `write` 和 3 次 `exit`。另一批次依次执行地址零写入、`sret` 和读取 `sstatus`，可沿异常入口观察应用切换。

[原参考构建](../reports/ucoreos/ch2/2026a/ucore-2026A-ch2-reference.html) · [栈地址修正版](../reports/ucoreos/ch2/2026a/ucore-2026A-ch2-stack-fixed.html) · [异常批次](../reports/ucoreos/ch2/2026a/ucore-2026A-ch2-faults.html)。原始记录、构建差异和命令见对应的 [录制信息](../reports/ucoreos/ch2/2026a/ucore-2026A-ch2-stack-fixed.json)。
