# rCore 实现

第七章通过描述符把管道接入文件接口，进程由此可以传递字节流。`dup` 和 `exec` 又使 shell 能够重定向标准输入输出。本节对应 [2026A 第七章参考实现](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/tree/c8e0313a55ed5926123d990f196061978c460aed)。

## 管道对象与描述符

[`make_pipe`](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/blob/c8e0313a55ed5926123d990f196061978c460aed/os/src/fs/pipe.rs) 创建一个环形缓冲区和两个 `Pipe` 对象。读端只允许读取，写端只允许写入；两个端点通过 `Arc` 共享缓冲区。

`sys_pipe` 为两个端点分配描述符，并把编号写回用户数组。`sys_dup` 给同一个文件对象增加一个描述符。`fork` 克隆描述符表后，父子进程仍引用同一组管道端点，写入的一方和读取的一方因而能够共享缓冲区。

## 环形缓冲区

[`PipeRingBuffer`](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/blob/c8e0313a55ed5926123d990f196061978c460aed/os/src/fs/pipe.rs#L57) 有 32 个字节槽。`head` 指向下一次读取的位置，`tail` 指向下一次写入的位置，两者到达数组末尾后从 0 继续。

当 `head == tail` 时，缓冲区可能为空，也可能已满。`status` 用 `Empty`、`Normal`、`Full` 区分这三种状态。满状态下 32 个槽都能保存数据。例如 `head = 28`、`tail = 4` 且状态为 `Normal` 时，未读数据跨过数组末尾，共有 8 字节。

## 读写与调度

`Pipe::write` 把用户缓冲区的字节依次写入环形缓冲区。空间用尽时，它释放缓冲区的动态借用，调用 `suspend_current_and_run_next`，恢复后再检查可写空间。已经写入的字节数保存在本次调用的局部变量中。

`Pipe::read` 在没有数据、写端仍存在时以同样方式让出处理器。写端全部关闭后，读端先取完缓冲区中剩余的数据，再以短读或 0 表示文件结束。零长度的读写直接返回 0。

这里的等待使用任务让出：任务保持就绪，调度器以后还会再次选择它。管道读写函数从原来的循环位置继续，而不是重新进入系统调用。

## 端点关闭与资源释放

`sys_close` 移除描述符中的引用。缓冲区保存指向写端的 `Weak` 引用；最后一个写端强引用释放后，`all_write_ends_closed` 才会返回真。父子进程或重复描述符保留的写端都计入端点的生命周期。

这版 `Pipe::write` 只检查剩余空间，没有检测读端是否全部关闭。读端消失后，写端仍会填满现有空间；此后的写入继续等待可写空间。代码中没有发送 `SIGPIPE` 的路径。

## 用户地址与失败处理

`sys_read` 和 `sys_write` 从描述符表取出端点，检查读写权限，再把用户缓冲区按页转换为切片。管道接口按切片顺序处理字节，环形缓冲区的下标与用户页边界各自独立推进。

描述符越界、空槽或读写方向不符时，系统调用返回 `-1`。`sys_pipe` 将两个描述符编号分别写到用户提供的两个 `usize` 位置；调用者需要提供有效的结果地址。

## 程序执行与通信

### 标准输入输出重定向

`exec` 替换地址空间时保留描述符表。shell 可以先在子进程中打开输出文件，关闭描述符 1，再用 `dup` 把文件对象放入这个最小空槽，然后执行目标程序。目标程序写标准输出时，字节便进入该文件。输入重定向对描述符 0 使用相同的办法。

### 信号处理

`kill` 把信号加入目标进程的待处理集合。异常处理路径检查信号及屏蔽状态；执行用户处理函数前，内核备份当前异常上下文，把 `sepc` 改成处理函数入口、把 `a0` 改成信号编号。用户处理函数通过 `sigreturn` 恢复备份的上下文。

`SIGSTOP` 使进程反复让出处理器，`SIGCONT` 解除停止状态。`fork` 复制屏蔽位和处理动作表，子进程从空的待处理集合开始。

## 运行观察

基础报告包含一次 3000 字节的管道通信。32 字节缓冲区会多次写满、读空；沿 `write_byte`、`read_byte` 和 `suspend_current_and_run_next` 的调用链，可以找到两个进程交替推进读写的位置。

重定向记录运行 `ch2b_hello_world > nfout`，程序输出写入磁盘文件 `nfout`。信号记录则可沿 `call_user_signal_handler → sys_sigreturn` 查看进入用户处理函数和恢复上下文的过程。

[管道报告](../reports/rcore/ch7/2026a/rcore-2026A-ch7-basic-observed.html) · [跨进程信号](../reports/rcore/ch7/2026a/rcore-2026A-ch7-signals-peer-observed.html) · [信号处理](../reports/rcore/ch7/2026a/rcore-2026A-ch7-signals-all-observed.html) · [重定向报告](../reports/rcore/ch7/2026a/rcore-2026A-ch7-redirect-observed.html) · [录制数据](../reports/rcore/ch7/2026a/recording.json)
