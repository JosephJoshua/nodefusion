# rCore 实现

源码固定到 [`ef2dfc4`](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/tree/ef2dfc4c23c70a1eb4c6a0b30feb694b2d09a73d) 的 `ch4-api-impl`。内存管理入口位于 [`os/src/mm`](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/tree/ef2dfc4c23c70a1eb4c6a0b30feb694b2d09a73d/os/src/mm)。

## 页表与物理页

[`PageTable`](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/blob/ef2dfc4c23c70a1eb4c6a0b30feb694b2d09a73d/os/src/mm/page_table.rs) 保存根页表号 `root_ppn` 与页表页的 `FrameTracker` 数组 `frames`。`new` 分配根页表，查找过程中缺少中间页表时，`find_pte_create` 分配并记录新的页表页。

`map` 查到末级项后检查其有效位。已有映射返回 `None`；空项写入目标物理页号、请求权限与 `V`。`unmap` 将有效末级项清零。它管理页表项，数据页的释放由调用方负责。

物理页由 [`StackFrameAllocator`](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/blob/ef2dfc4c23c70a1eb4c6a0b30feb694b2d09a73d/os/src/mm/frame_allocator.rs) 分配。新分配的 `FrameTracker` 将页清零，析构时归还页号。`PageTable::from_token` 创建页表视图，`frames` 为空，因此临时查找视图不会释放实际页表。

## 装载与地址空间

[`MemorySet`](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/blob/ef2dfc4c23c70a1eb4c6a0b30feb694b2d09a73d/os/src/mm/memory_set.rs) 包含页表和 `MapArea` 数组。区域保存虚拟页范围、权限和映射类型。`Framed` 区域为各虚拟页分配数据页，并用 `data_frames` 保存所有权；`Identical` 区域使用相同的虚拟页号和物理页号。

`from_elf` 读取各个非空 `PT_LOAD` 段，按 ELF 的读写执行标志设置权限，并加上 `U`。文件内容复制到实际段起始地址，段内剩余空间保留为零。最高段结束页之后留一页空隙，再建立读写用户栈。栈顶也是初始堆边界，堆区域开始时长度为零。

异常上下文放在跳板下一页，权限为 `RW`，没有 `U`。跳板映射到内核的 `strampoline`，权限为 `RX`，同样没有 `U`。各应用使用独立数据页，跳板代码共享。

## 异常入口与页表切换

[`trap.S`](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/blob/ef2dfc4c23c70a1eb4c6a0b30feb694b2d09a73d/os/src/trap/trap.S) 的 `__alltraps` 在用户页表下保存寄存器，从异常上下文取得内核 `satp`、内核栈和处理函数地址，切换页表后跳入 Rust 处理代码。

返回路径准备用户页表令牌，将执行位置转移到跳板中的 `__restore`。它先写用户 `satp` 并执行 `sfence.vma`，随后从异常上下文恢复用户寄存器，执行 `sret`。

## 用户地址检查

`translate_user` 首先检查地址能否按 Sv39 规则转换后原样还原，然后要求末级项同时包含 `V`、`U` 与请求权限。返回值保留页内偏移。

[`sys_trace`](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/blob/ef2dfc4c23c70a1eb4c6a0b30feb694b2d09a73d/os/src/syscall/process.rs) 读取用户字节时请求 `R`，写入时请求 `W`。`sys_get_time` 检查整个输出范围的写权限，再按页分段复制 `TimeVal`，避免跨页缓冲区只写入一部分。

`translated_byte_buffer` 用于把虚拟连续缓冲区分成物理页内的切片，它检查映射有效性。`sys_write` 本章使用这个函数，其路径没有调用 `translate_user` 检查用户读权限。阅读系统调用时，需要沿具体调用链查看检查位置。

## 映射与回收

`sys_mmap` 检查起始地址页对齐、权限位、长度计算溢出和 Sv39 地址范围，任务层随后检查区域是否已有映射。成功后建立带 `U` 的 `Framed` 区域。

`sys_munmap` 进入任务层，再调用 `remove_framed_area`。本提交按完整区域匹配起止页号；部分区域和跨区域请求无法找到匹配项。成功撤销时，`MapArea::unmap` 清除各页表项，并移除对应的 `FrameTracker`，归还数据页。

`sys_sbrk` 调整堆边界。扩展时补充分配数据页，缩小时撤销不再需要的页。区域边界按页向上取整，因此小于一页的边界变化可能不改变物理页数量。

任务退出只将状态设为 `Exited`。本章全局任务数组仍持有控制块和 `MemorySet`，没有在退出路径完整销毁地址空间。

## 运行观察

本次装载第二至四章的 21 个应用。观察版内核与参考内核内嵌的 21 份用户 ELF 校验值完全相同。录制覆盖启动、应用运行、异常处理和关机。

| 观察点 | 次数 |
| --- | ---: |
| `mmap` 系统调用 | 13 |
| `munmap` 系统调用 | 4 |
| `sbrk` 系统调用 | 8 |
| `trace` 系统调用 | 24 |
| 成功撤销完整区域 | 2 |
| 撤销单页映射 | 13 |
| 归还数据物理页 | 13 |

13 次单页撤销中，2 次来自 `munmap`，11 次来自缩小堆。物理页分配器记录 496 次分配和 13 次归还，最终使用量增加 483 页，与两者之差一致。

六个应用因异常退出，其余十五个正常退出。三次写访问触发缺页异常，地址分别为 `0`、`0x10000000` 和 `0xc000`；一次读访问在 `0x10000000` 触发缺页异常。另两次非法指令异常先进入 M 模式，由 OpenSBI 转交内核处理。它们来自异常类测试，与内存映射的正常返回路径分开查看。

[打开运行报告](../reports/rcore/ch4/2026a/rcore-2026A-ch4-observed.html)。选择映射、撤销映射或物理页事件，再查看参数和前后状态。函数视图可沿系统调用、内存区域、页表和分配器逐层定位。

<details>
<summary>构建与录制参数</summary>

用户程序提交为 `a0593662ad55d670ba8c27ce1763347cd0dd552f`，Rust 使用 `nightly-2024-05-02`，QEMU 为 10.2.2。观察补丁保留独立入口，并在实际分配和归还之后记录物理页地址与计数。

内核 ELF 的 SHA-256 为 `2851a05dc0e377c07ee76da70426ba3c17b0bbf42594af5215dd8bd48ef80925`。构建命令、完整录制参数、原始轨迹校验值和报告分析版本见[运行数据](../reports/rcore/ch4/2026a/recording.json)。

</details>
