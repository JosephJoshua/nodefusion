# rCore 实现

第四章为每个应用建立独立的虚拟地址空间。页表负责地址转换，`MemorySet` 负责组织代码、数据、栈和堆所在的区域。源码采用 [2026A 第四章参考实现](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/tree/ef2dfc4c23c70a1eb4c6a0b30feb694b2d09a73d)。

## 页表与物理页

[`PageTable`](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/blob/ef2dfc4c23c70a1eb4c6a0b30feb694b2d09a73d/os/src/mm/page_table.rs) 保存根页表页号。建立映射时，`find_pte_create` 沿 Sv39 的多级页表向下查找，按需分配中间页表页，`map` 再写入末级页表项。`unmap` 清除末级页表项；数据页由上层的内存区域管理。

物理页分配器返回 `FrameTracker`。新分配的页会清零，`FrameTracker` 析构时归还页号。页表持有自己的页表页，`Framed` 类型的内存区域持有应用数据页。两类页各由相应的所有者负责释放。

## 装载与地址空间

[`MemorySet::from_elf`](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/blob/ef2dfc4c23c70a1eb4c6a0b30feb694b2d09a73d/os/src/mm/memory_set.rs#L291) 遍历 ELF 中非空的 `PT_LOAD` 段，按段的读、写、执行标志建立用户映射，再将文件内容复制到段的虚拟地址。新页已经清零，段在文件内容之后的内存部分保持为零。

最高的装载段之后留出一个未映射页，再建立用户栈。栈顶也是初始堆边界。内核还把异常上下文映射到跳板下方一页，把跳板代码映射到固定的高地址；这两处映射没有用户访问权限。

## 异常入口与页表切换

异常发生时，处理器仍使用用户页表。跳板中的 `__alltraps` 先把用户寄存器保存到异常上下文，从中取得内核页表令牌、内核栈指针和异常处理函数地址，然后切换 `satp`，进入 Rust 处理代码。

返回用户态时，`__restore` 在跳板中切回用户页表，执行 `sfence.vma`，恢复寄存器，最后执行 `sret`。跳板在两个地址空间中映射到相同的虚拟地址，页表切换前后的指令流因而能连续执行。

## 用户地址检查

[`translate_user`](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/blob/ef2dfc4c23c70a1eb4c6a0b30feb694b2d09a73d/os/src/mm/page_table.rs#L201) 检查地址是否符合 Sv39 格式，再检查页表项的有效位、用户位和请求的读写权限。返回的物理地址保留页内偏移。

`sys_trace` 读取用户字节时请求读权限，写入时请求写权限。`sys_get_time` 先检查整个输出范围，再逐页写入 `TimeVal`。跨越页边界的用户缓冲区需要分别检查每个页表项。

## 映射与回收

`sys_mmap` 检查起始地址、长度和权限，建立用户可访问的 `Framed` 区域。`sys_munmap` 调用 [`remove_framed_area`](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/blob/ef2dfc4c23c70a1eb4c6a0b30feb694b2d09a73d/os/src/mm/memory_set.rs#L394)；这一版实现按区域的起止页号查找，要求一次撤销完整区域。找到区域后，内核清除页表项并归还其数据页。

`sys_sbrk` 改变堆边界。边界跨过页时才需要增加或撤销数据页；同一页内的变化只更新逻辑边界。

## 运行观察

报告中可沿 `sys_munmap → munmap_current_task → remove_framed_area → MapArea::unmap` 查看一次完整区域撤销。页表项清除与 `FrameTracker` 归还随后发生。`sbrk` 缩小堆时也会出现单页撤销，但调用链从堆区域的 `shrink_to` 开始。

运行的 21 个应用还包括故意访问未映射地址的程序。它们触发的缺页异常进入异常处理路径；成功的 `mmap` 和 `munmap` 则沿系统调用路径返回用户态。

[查看内存管理报告](../reports/rcore/ch4/2026a/rcore-2026A-ch4-observed.html) · [录制数据](../reports/rcore/ch4/2026a/recording.json)
