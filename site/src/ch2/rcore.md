# rCore 实现

本节分析课程仓库 `ch2-api-impl` 的提交 [`529d8ba`](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/tree/529d8bafef3dea5489c85a565d912307f6bbccb7)。应用测试来自 [`a059366`](https://github.com/LearningOS/rCore-Tutorial-Test/tree/a0593662ad55d670ba8c27ce1763347cd0dd552f)。

## 批次状态与装载

[`AppManager`](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/blob/529d8bafef3dea5489c85a565d912307f6bbccb7/os/src/batch.rs#L50) 保存应用数 `num_app`、下一应用序号 `current_app` 和应用位置数组 `app_start`。数组中每两个相邻地址界定一个二进制的范围；额外的最后一个地址用于计算最后一个应用的大小。

管理器由 `lazy_static` 初始化，读取链接时生成的 `_num_app` 表。`UPSafeCell` 提供对内部状态的可变访问。`run_next_app` 取得当前序号，调用 `load_app`，将序号增加一，再释放动态借用。

因此，应用 0 已经运行时，`current_app` 的值为 1。报告中的“下一应用序号”对应这一含义。

[`load_app`](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/blob/529d8bafef3dea5489c85a565d912307f6bbccb7/os/src/batch.rs#L69) 清零从 `0x80400000` 开始的 `0x20000` 字节，将选中应用复制到同一区域，随后执行 `fence.i`，使后续取指能够观察到刚写入的程序。序号等于应用数时，函数输出批次完成信息并结束虚拟机。

## 首次进入用户态

[`TrapContext::app_init_context`](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/blob/529d8bafef3dea5489c85a565d912307f6bbccb7/os/src/trap/context.rs) 将入口设为 `0x80400000`，将保存的 `sp` 设为用户栈顶，并把 `sstatus.SPP` 设为用户模式。

用户栈和内核栈各有 8 KiB，按页对齐。`KERNEL_STACK.push_context` 将上下文写到内核栈顶下方，再把它的地址传给 `__restore`。恢复汇编使用这个预先建立的上下文进入第一个应用。此时还没有发生过用户异常。

## 异常入口与上下文

[`trap.S`](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/blob/529d8bafef3dea5489c85a565d912307f6bbccb7/os/src/trap/trap.S) 的 `__alltraps` 首先交换 `sp` 与 `sscratch`。交换后，`sp` 指向内核栈，原用户栈指针留在 `sscratch` 中。入口为 `TrapContext` 预留 272 字节，保存寄存器、`sstatus` 和 `sepc`，再把上下文地址放入 `a0`，调用 `trap_handler`。

`TrapContext` 为 32 个通用寄存器提供槽位，另有两个控制状态字段。该章汇编跳过 `x4`（`tp`）；零寄存器也无需保存。用户栈指针则从 `sscratch` 读出，写入 `x[2]`。

返回时，`__restore` 从上下文恢复 `sstatus`、`sepc` 和通用寄存器，再交换栈指针并执行 `sret`。用户上下文位于内核栈的高地址端，处理函数的调用栈向低地址增长。

## 系统调用与返回

[`trap_handler`](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/blob/529d8bafef3dea5489c85a565d912307f6bbccb7/os/src/trap/mod.rs#L63) 对用户 `ecall` 执行两项更新：

```rust
cx.sepc += 4;
cx.x[10] = syscall(cx.x[17], [cx.x[10], cx.x[11], cx.x[12]]) as usize;
```

`x[17]` 是 `a7`，`x[10..=12]` 是三个参数。普通调用返回后，处理函数将同一个上下文交给恢复汇编。

[`sys_write`](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/blob/529d8bafef3dea5489c85a565d912307f6bbccb7/os/src/syscall/fs.rs) 只接受文件描述符 1，把缓冲区解释为 UTF-8 字符串并输出，成功时返回长度。不支持的描述符、无效的 UTF-8 和未知系统调用号会进入 panic 路径。该实现直接根据地址和长度构造切片，尚未进行用户缓冲区范围检查。

## 退出与应用异常

[`sys_exit`](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/blob/529d8bafef3dea5489c85a565d912307f6bbccb7/os/src/syscall/process.rs) 输出退出码后调用 `run_next_app`。这个函数不会返回原用户上下文。

异常分发对 `StoreFault`、`StorePageFault` 和 `IllegalInstruction` 输出诊断信息，然后装载下一应用。其他原因会 panic。日志中的 `PageFault` 消息同时用于前两种原因；本次向地址零写入产生的是原因 7，即存储访问异常。

## 运行观察

本次运行按名称顺序装载七个第二章应用：三个异常程序、Hello World，以及三个求幂程序。三个异常程序分别向地址零写入、执行 `sret`、读取特权寄存器。其余四个应用通过退出系统调用结束。

第一条 write 位于第 11,648,879 条指令：`a7 = 64`，`a0 = 1`，`a2 = 37`。第 11,648,920 条指令处进入 `trap_handler`，其 `a0` 与 `sp` 均为上下文地址 `0x80206ef0`。入口汇编已把用户参数写入该上下文，处理函数通过上下文读取它们。

| 观察点 | 完整轨迹中的次数 |
| --- | ---: |
| 用户 write，系统调用 64 | 61 |
| 用户 exit，系统调用 93 | 4 |
| `trap_handler` | 68 |
| `run_next_app` | 8 |

68 次异常处理由 65 次系统调用和三次应用异常组成。七次装载应用加上最后一次批次结束检查，共进入 `run_next_app` 八次。最后输出 `All applications completed!`，运行正常结束。

[打开本次运行报告](../reports/rcore/ch2/2026a/rcore-2026A-ch2-reference.html)。在函数轨迹中筛选 `trap_handler` 或 `run_next_app`，再结合系统调用参数与“下一应用序号”查看批次推进。

<details>
<summary>构建与录制参数</summary>

内核源码未修改。用户应用使用 `CHAPTER=2 TEST=2 BASE=2` 构建；内核使用 Rust `1.80.0-nightly`，以 `LOG=TRACE CARGO_PROFILE_RELEASE_DEBUG=2 cargo build --release` 保留调试信息。QEMU 为 10.2.2，固件为 OpenSBI 1.7。

实际录制命令在远程任务的 `tool` 目录执行：

```sh
/home/joseph/nf/venv313/bin/python -m nodefusion.host.cli record \
  --kernel /home/joseph/nf/education-2026A-20260927/rcore-ch2 \
  --kernel-kind rcore --runs /home/joseph/nf/education-2026A-20260927/runs \
  --name rcore-2026A-ch2-reference --no-build --function-returns --watch-all \
  --profile uniform --snapshots 80 --max-ram-bytes 268435456 \
  --timeout 60 --no-render --event-stream never
```

轨迹包含 7,167 条事件和 2,346 条函数入口，报告全部保留。完整构建环境、工具源码补丁、分析命令与校验和见[录制参数](../reports/rcore/ch2/2026a/rcore-2026A-ch2-reference.json)，输出见[串口日志](../reports/rcore/ch2/2026a/rcore-2026A-ch2-reference.log)。

</details>

## 源码阅读练习

1. 应用 3 开始执行时，`current_app` 为什么是 4？最后一次 `run_next_app` 会在哪一行结束运行？
2. 沿 `__alltraps` 找到用户 `sp` 的保存位置，说明处理函数为什么可以使用另一个栈。
3. 如果删去 `cx.sepc += 4`，一次 write 返回后会执行哪条指令？
4. 设 write 返回 `-1`，将其转换为 `usize` 再恢复到 `a0` 后，用户端如何取得有符号的返回值？
