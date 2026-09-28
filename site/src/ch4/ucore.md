# uCore 实现

源码固定到 [`51f0226`](https://github.com/LearningOS/uCore-Tutorial-Code-2026A/tree/51f02268653c68f169f5599055da3b0391995ee6) 的 `ch4-api-impl`。页表函数位于 [`os/vm.c`](https://github.com/LearningOS/uCore-Tutorial-Code-2026A/blob/51f02268653c68f169f5599055da3b0391995ee6/os/vm.c)。

## 页表与物理页

`pagetable_t` 指向根页表所在的物理页。`walk(pagetable, va, alloc)` 根据三个索引逐层查找，返回末级页表项的地址。中间项缺失时，`alloc = 0` 返回空指针；`alloc = 1` 分配新页，清零后把地址写入上层项。

`mappages` 将虚拟范围按页覆盖。它用 `walk` 找到每个末级项，检查已有映射，再写入物理地址和权限。`uvmunmap` 逐页清除末级项，`do_free` 决定是否调用 `kfree` 归还数据页。

[`kalloc.c`](https://github.com/LearningOS/uCore-Tutorial-Code-2026A/blob/51f02268653c68f169f5599055da3b0391995ee6/os/kalloc.c) 使用空闲页链表。分配后将整页填为字节值 5，归还时填为 1，再加入链表。因此，建立新页表的调用方需要显式清零页表页。

## 装载与地址空间

[`bin_loader`](https://github.com/LearningOS/uCore-Tutorial-Code-2026A/blob/51f02268653c68f169f5599055da3b0391995ee6/os/loader.c) 为每个进程创建用户页表，将内核中嵌入的应用二进制直接映射到 `BASE_ADDRESS`。代码和数据的这段映射统一使用 `RWXU`。

装载范围后留一页空隙，再分配一页用户栈，栈也使用 `RWXU`。`trapframe` 的物理页映射到 `TRAPFRAME`，权限为 `RW`，没有 `U`。跳板映射到 `TRAMPOLINE`，权限为 `RX`，没有 `U`。

每个进程有独立根页表。应用代码使用已嵌入内核的物理页，用户栈由分配器提供。进程中的 `program_brk` 与 `heap_bottom` 初始化为用户栈顶。

## 异常入口与页表切换

[`trampoline.S`](https://github.com/LearningOS/uCore-Tutorial-Code-2026A/blob/51f02268653c68f169f5599055da3b0391995ee6/os/trampoline.S) 的 `uservec` 用 `sscratch` 取得异常上下文的虚拟地址，保存用户寄存器与 `sepc`。随后读取内核栈、处理入口和内核页表，写入 `satp`，执行 `sfence.vma`，跳转到内核处理函数。

`userret` 接收 `TRAPFRAME` 和用户页表令牌，切换用户页表后恢复寄存器。最后交换 `a0` 与 `sscratch`，恢复用户 `a0`，并为下一次异常保留上下文地址。

## 用户地址检查

`walkaddr` 检查地址小于 `MAXVA`、页表项有效且设置 `U`，返回物理页起始地址。`useraddr` 再拼接原虚拟地址的低 12 位，得到字节地址。

`copyin` 与 `copyout` 按页复制，使用 `walkaddr` 检查每一页。这个提交的 `walkaddr` 没有区分请求的读写权限，所以这两个函数也没有分别检查 `R` 和 `W`。

## 映射与回收

`uvmunmap` 的 `do_free = 0` 只撤销映射，数据页继续由调用方持有。`do_free = 1` 在清除页表项前归还数据页。`freewalk` 递归释放页表页，要求所有末级映射已经撤销；仍发现有效叶项时会触发错误。

[`syscall.c`](https://github.com/LearningOS/uCore-Tutorial-Code-2026A/blob/51f02268653c68f169f5599055da3b0391995ee6/os/syscall.c) 中的 `mmap`、`munmap` 和 `trace` 仍为实验待实现接口。已有 `sys_sbrk` 使用 `uvmalloc` 或 `uvmdealloc` 改变堆范围。

进程退出调用 [`freeproc`](https://github.com/LearningOS/uCore-Tutorial-Code-2026A/blob/51f02268653c68f169f5599055da3b0391995ee6/os/proc.c)。其中 `uvmfree` 调用被注释，退出只恢复进程槽位状态，没有执行完整地址空间回收。

## 运行观察

原批次运行六个基础应用，输出、让出处理器和退出的课程检查通过。物理页记录包含 103 次分配，运行阶段没有归还；六个应用也没有执行 `uvmunmap`。

[打开基础批次报告](../reports/ucoreos/ch4/2026a/ucore-2026A-ch4-observed.html)。可以查看用户页表根地址、跳板入口和分配过程。初始化空闲链表时的 `kfree` 调用发生在分配器启用之前，运行阶段的归还计数从初始化结束后开始。

另一次录制在加载同样六个应用之前，运行独立页表实验：创建临时页表，将 `0x4000` 映射到物理页 `0x87fb9000`，权限为 `RWU`，检查偏移 `0x123` 处的字节 `0x5a`。

| 累计指令数 | 操作 | 结果 |
| ---: | --- | --- |
| 412,991,763 | 首次建立数据页映射 | 末级项权限为 `0x17`，包含 `V/R/W/U` |
| 413,037,577 | `uvmunmap(..., 0x4000, 1, 0)` | 映射撤销，数据页保留 |
| 413,067,814 | 重建映射后，`uvmunmap(..., 0x4000, 1, 1)` | 映射撤销，同一数据页归还 |
| 413,110,301 | 撤销跳板映射，`do_free = 0` | 共享跳板的物理页继续保留 |

实验创建的五个页表页和一个数据页全部归还，分配与归还地址逐一对应。实验前后的空闲页数均为 32,103，使用页数均为 67。随后六个基础应用继续执行，课程检查通过。

[打开页表实验报告](../reports/ucoreos/ch4/2026a/ucore-2026A-ch4-pagetable.html)。将时间定位到表中第一项，筛选 `vm.unmap` 和物理页事件，比较两种 `do_free` 参数下的记录。

<details>
<summary>构建与录制参数</summary>

用户程序提交为 `1733f460c596b013b1c509ad42afa428640783b0`，使用 GCC 14.2.0、CMake 3.31.6 和 QEMU 10.2.2。两次运行使用相同的六份用户二进制。

基础观察版 ELF 的 SHA-256 为 `b2eacf484a2474f835578ba0764ac9e0b07f9a5ae878f6f5270e408dfef1e7c1`，实验版为 `21ed16ef2f7c3e3cc78658073e20542ae65ea400c00447860eddb042d4a6a327`。源码补丁、构建命令和录制参数分别见[批次数据](../reports/ucoreos/ch4/2026a/recording.json)与[实验数据](../reports/ucoreos/ch4/2026a/ucore-2026A-ch4-pagetable.json)。

</details>
