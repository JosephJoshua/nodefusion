# rCore 实现

源码固定到 [`c8e0313`](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/tree/c8e0313a55ed5926123d990f196061978c460aed) 的 `ch7-api-impl`。管道位于 `os/src/fs/pipe.rs`，描述符接口位于 `os/src/syscall/fs.rs`。

## 管道对象与描述符

[`Pipe`](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/blob/c8e0313a55ed5926123d990f196061978c460aed/os/src/fs/pipe.rs) 实现 `File` 接口，保存读写权限和 `Arc<UPSafeCell<PipeRingBuffer>>`。`make_pipe` 新建一个缓冲区和两个端点，两个端点分别只读、只写，共享缓冲区。

缓冲区保存指向写端的 `Weak<Pipe>`。它可以通过 `upgrade` 检查写端是否仍存在，同时避免缓冲区和写端相互持有强引用。

`sys_pipe` 先取得最小空闲描述符并放入读端，再取得最小空闲描述符并放入写端，最后向用户数组写回两个 `usize`。已占用的槽保持不变。描述符表用 `Vec` 保存，找不到空槽时扩展一个槽。

`sys_dup` 克隆原文件对象的 `Arc`，放到新的最小空槽。两个描述符访问同一对象；普通文件的偏移和管道端点的生命周期都由该对象保存。参数越界或原槽为空时返回 `-1`。

## 环形缓冲区

`PipeRingBuffer` 的数组有 32 个字节。`head` 指向下一读取位置，`tail` 指向下一写入位置。`write_byte` 写入后推进 `tail`，`read_byte` 取出后推进 `head`，下标均对 32 取余。

当两个下标相等时，缓冲区既可能为空，也可能已满。`status` 保存 `Empty`、`Normal` 或 `Full`，区分这两种情况。正常状态下，可读量为 `(tail + 32 - head) % 32`；空状态为 0，满状态为 32。可写量始终为 `32 - 可读量`。

例如 `head = 28`、`tail = 4`、状态为 `Normal`，未读数据分布在下标 28–31 和 0–3，共 8 字节。再读取 8 字节后，`head` 到达 4，状态变为 `Empty`。这个实现可以使用数组的全部 32 个槽。

## 读写与调度

`sys_read` 和 `sys_write` 检查描述符及访问权限，取得文件对象引用后释放任务控制块的借用，再调用管道接口。

写入循环保存已经写入的字节数。只要有空闲空间，就通过 `write_byte` 逐字节写入；缓冲区满时，先释放缓冲区借用，再调用 `suspend_current_and_run_next`。恢复运行后重新检查空间，直到完成整个请求。

读取循环同样保存进度。缓冲区中有数据时，读取请求剩余长度与可读量的较小值；缓冲区空且仍有写端时，释放借用并让出处理器。只有写端全部消失且缓冲区读空，函数才提前返回已读长度。零长度读写立即返回 0。

释放借用使另一个进程能够访问共享缓冲区。调度路径把当前任务改为 `Ready`，放回就绪队列，随后进入调度器。内核再次选中它时，从原读写循环继续；这次系统调用尚未返回用户态。

## 端点关闭与资源释放

`fork` 克隆描述符表中的强引用。`sys_close` 取走一个槽中的引用，退出路径清空整个描述符表。读写系统调用取得的临时文件引用也会延长端点的生命周期，直到这次调用结束。

`all_write_ends_closed` 检查缓冲区中的弱引用。父进程关闭一个写描述符后，子进程或重复描述符仍可能持有写端；此时 `upgrade` 仍能成功。最后一个写端强引用释放后，读进程仍可取走缓冲区中的残留数据。

两个端点都释放后，缓冲区的强引用计数归零，堆对象随之释放。管道的读写位置保存在缓冲区中，所有使用同一读端的进程共同推进 `head`。

写入循环只检查剩余空间，没有检查读端是否已关闭。若读端全部消失，写进程仍可填入现有空间，缓冲区满后反复让出处理器。这个路径不会产生 `SIGPIPE`。

## 用户地址与失败处理

`translated_byte_buffer` 按用户页表把缓冲区拆成若干页内切片，`UserBufferIterator` 按虚拟地址顺序逐字节访问它们。管道接口收到的是这些已经转换的切片，环形数组的下标与用户页边界分别更新。

`sys_pipe` 的结果是两个对齐的 `usize`。两项分别通过 `translated_refmut` 转换，因此可以分别位于相邻用户页。该接口的输入约定要求这两个位置有效、可写，并且分配成功；页表查询返回 `None` 时，`unwrap` 会触发 panic。这条创建路径没有分配失败回滚。

描述符检查与地址检查分别发生在不同层次。越界描述符、空槽、用读端写入或用写端读取由系统调用返回 `-1`。`translated_byte_buffer` 本身没有对每页检查完整的用户读写权限，可以与第四章的页表权限位一起检查这条访问路径。

## 程序执行与通信

### 标准输入输出重定向

`exec` 替换用户地址空间，保留文件描述符表。shell 因而可以先修改子进程的标准输入输出，再装入目标程序。

本版本的 shell 解析 `<` 和 `>`。输出重定向在子进程中打开目标文件，关闭描述符 1，再调用 `dup`。最小空槽此时为 1，复制的文件对象成为标准输出；随后关闭原描述符并执行目标程序。输入重定向对描述符 0 做同样处理。这个 shell 没有解析 `|`，课程管道用例直接调用管道接口。

### 信号处理

进程保存待处理信号位图、屏蔽位图和处理动作表。`kill` 向目标进程的待处理位图插入一个信号；同一信号已经待处理时返回 `-1`。内核在异常处理路径中检查信号及屏蔽状态。

调用用户处理函数时，`call_user_signal_handler` 备份异常上下文，把 `sepc` 改为处理函数地址，把 `a0` 改为信号编号。处理函数通过 `sigreturn` 恢复备份上下文；返回原 `a0`，使系统调用返回路径保持被中断时的寄存器值。

`SIGSTOP` 设置 `frozen`，处理循环反复让出；`SIGCONT` 清除该标志。终止信号由错误检查路径转换为退出码。`fork` 复制屏蔽位和动作表，子进程的待处理位图初始化为空；`exec` 保留这些信号字段。此结构只保存一份 `trap_ctx_backup`，分析嵌套处理时需要追踪备份是否被覆盖。

## 运行观察

基础批次执行 `ch7b_usertest` 的 16 个课程测试，其中包含 13 字节管道、3000 字节双向通信和简单信号测试。初始磁盘中的 65 个用户 ELF 与参考构建逐项相同，运行后这些文件保持不变。

完整原始流中，三个不同缓冲区分别记录 13、3000 和 5 次 `write_byte`，以及相同数量的 `read_byte`。3018 次写入和 3018 次读取都匹配到了函数返回记录。结合初始空状态，按每次完成的操作计算未读量，3000 字节管道的峰值达到 32 字节，出现 93 次进入满状态、94 次进入空状态，结束时为空。5 字节返回管道传递校验和文本 `81000`。

| 观察点 | 基础批次 |
| --- | ---: |
| `write_byte` 完成次数 | 3,018 |
| `read_byte` 完成次数 | 3,018 |
| `available_read` 入口 | 420 |
| `available_write` 入口 | 189 |
| `all_write_ends_closed` 入口 | 135 |
| 物理页分配 / 归还 | 1,595 / 1,485 |
| 分配器使用页数峰值 / 结束值 | 745 / 110 |

另两份记录运行已有的 `ch7b_sig_simple2` 和 `ch7b_sig_tests`。后者依次完成 8 个信号子测试，原始流中记录了 3 次用户信号处理入口与 3 次 `sys_sigreturn`。重定向记录执行 `ch2b_hello_world > nfout`，捕获 1 次 `sys_dup`；磁盘中留下 36 字节的 `nfout`，内容与原程序输出一致。

在函数视图中搜索 `write_byte`、`read_byte` 和 `suspend_current_and_run_next`，结合任务身份查看读写交错；搜索 `call_user_signal_handler` 和 `sys_sigreturn` 查看信号处理与上下文恢复。返回记录用于匹配函数控制流，写入字节来自入口参数，数据校验由用户用例完成。

[打开基础测试报告](../reports/rcore/ch7/2026a/rcore-2026A-ch7-basic-observed.html) · [打开跨进程信号报告](../reports/rcore/ch7/2026a/rcore-2026A-ch7-signals-peer-observed.html) · [打开信号测试报告](../reports/rcore/ch7/2026a/rcore-2026A-ch7-signals-all-observed.html) · [打开重定向报告](../reports/rcore/ch7/2026a/rcore-2026A-ch7-redirect-observed.html)

<details>
<summary>构建与录制参数</summary>

用户程序固定到 [`a059366`](https://github.com/LearningOS/rCore-Tutorial-Test/tree/a0593662ad55d670ba8c27ce1763347cd0dd552f)。观察版使用 `rcore-2026a-ch7-observation.patch`，保留管道缓冲区和信号处理入口，并记录物理页、fork、调度和区域解除映射。用户 ELF 直接复制参考构建的产物。

工具链为 `nightly-2024-05-02`，QEMU 为 10.2.2；内核使用 `LOG=TRACE CARGO_PROFILE_RELEASE_DEBUG=2 cargo build --release --locked`。四份记录分别从初始磁盘副本运行，参数均包含 `--no-build --function-returns --watch-all --profile uniform --snapshots 80 --max-ram-bytes 268435456 --timeout 600 --no-render --event-stream never`。

四次 `--program` 参数依次为 `ch7b_usertest`、`ch7b_sig_simple2`、`ch7b_sig_tests` 和 `ch2b_hello_world > nfout`，重定向命令作为一个参数传入。批次名称、实际构建与分析命令、完整原始计数、来源归档和前后磁盘校验值保存在[基础记录](../reports/rcore/ch7/2026a/recording.json)、[跨进程信号记录](../reports/rcore/ch7/2026a/rcore-2026A-ch7-signals-peer-observed.json)、[信号测试记录](../reports/rcore/ch7/2026a/rcore-2026A-ch7-signals-all-observed.json)和[重定向记录](../reports/rcore/ch7/2026a/rcore-2026A-ch7-redirect-observed.json)中。

</details>
