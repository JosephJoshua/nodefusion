# uCore 实现

第四章为每个进程建立独立页表。用户程序看到自己的虚拟地址空间；异常入口和返回汇编则负责在用户页表与内核页表之间切换。以下代码来自 [uCore 2026A 第四章](https://github.com/LearningOS/uCore-Tutorial-Code-2026A/tree/51f02268653c68f169f5599055da3b0391995ee6)。

## 页表与物理页

[`walk`](https://github.com/LearningOS/uCore-Tutorial-Code-2026A/blob/51f02268653c68f169f5599055da3b0391995ee6/os/vm.c) 根据 Sv39 的三级索引查找页表项。中间页表不存在时，`alloc = 1` 会分配并清零一页；`alloc = 0` 则返回空指针。`mappages` 逐页取得末级页表项，写入物理页号和权限。

物理页分配器是空闲页链表。`kalloc` 取出一页并填入字节 5，`kfree` 填入字节 1 后归还。新页表页必须由调用者清零，才能把所有页表项初始化为无效。

## 装载与地址空间

[`bin_loader`](https://github.com/LearningOS/uCore-Tutorial-Code-2026A/blob/51f02268653c68f169f5599055da3b0391995ee6/os/loader.c) 为进程创建用户页表，将嵌在内核映像中的应用映射到 `BASE_ADDRESS`，权限为 `R | W | X | U`。代码之后留一页空隙，再分配用户栈。

内核还把异常上下文页映射到 `TRAPFRAME`，权限为 `R | W`；把跳板映射到 `TRAMPOLINE`，权限为 `R | X`。这两处映射没有 `U`，用户态不能直接访问。各进程拥有自己的页表根，跳板的物理代码则由它们共享。

## 异常入口与页表切换

[`uservec`](https://github.com/LearningOS/uCore-Tutorial-Code-2026A/blob/51f02268653c68f169f5599055da3b0391995ee6/os/trampoline.S) 先在用户页表下保存寄存器，再从异常上下文取出内核页表和内核栈。写入 `satp`、执行 `sfence.vma` 后，才跳转到内核中的异常处理函数。

返回汇编 `userret` 先切回用户页表，再恢复用户寄存器，最后执行 `sret`。跳板同时映射在两套页表中，使切换 `satp` 前后的汇编指令能够继续执行。

## 用户地址检查

`walkaddr` 要求虚拟地址低于 `MAXVA`，页表项有效且带有 `U` 标志；`useraddr` 再加上页内偏移。`copyin`、`copyout` 按页界分段，每到下一页都重新查找映射。

本章的 `walkaddr` 没有分别检查 `R` 与 `W`。因此，这两个复制函数只验证页面可由用户访问，尚未按复制方向验证读写权限。

## 映射与回收

`uvmunmap` 清除末级页表项。参数 `do_free = 0` 只解除映射，物理页仍由调用者持有；`do_free = 1` 还调用 `kfree`。`freewalk` 递归释放页表页，要求叶子映射此前已经解除。

这个提交已实现 `sys_sbrk`，但 `mmap`、`munmap` 和 `trace` 仍留待后续实现。`freeproc` 中的 `uvmfree` 调用被注释：退出进程会恢复表项状态，却不会在这条路径上释放其整个地址空间。这一点可与下章的回收代码对照。

## 运行观察

页表实验将虚拟地址 `0x4000` 映射到物理页 `0x87fb9000`，写入并读回页内偏移 `0x123` 的字节 `0x5a`。接着分别以两种 `do_free` 参数撤销同一数据页的映射：

| 操作 | 物理页的处理 |
| --- | --- |
| `uvmunmap(..., 0x4000, 1, 0)` | 只清除页表项 |
| 重新映射后 `uvmunmap(..., 0x4000, 1, 1)` | 清除页表项并归还数据页 |

实验还以 `do_free = 0` 解除跳板映射，因为跳板代码不是这张临时页表独占的物理页。实验结束时，临时页表页和数据页均已归还，随后六个基础应用继续运行。

[基础批次](../reports/ucoreos/ch4/2026a/ucore-2026A-ch4-observed.html) · [页表实验](../reports/ucoreos/ch4/2026a/ucore-2026A-ch4-pagetable.html) · [录制信息](../reports/ucoreos/ch4/2026a/recording.json)
