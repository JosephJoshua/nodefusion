# rCore 实现

源码固定到 [`b47c54b`](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/tree/b47c54b5c1f3254518238b0c7450af9c187b4231) 的 `ch6-api-impl`。文件接口位于 `os/src/fs/`，磁盘布局、目录和缓存位于 `easy-fs/src/`。

## 文件对象与描述符

[`OSInode`](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/blob/b47c54b5c1f3254518238b0c7450af9c187b4231/os/src/fs/inode.rs) 包含读写权限和 `OSInodeInner`。内部状态保存 `offset` 与 `Arc<Inode>`；进程的 `fd_table` 持有实现 `File` 接口的对象。一次成功的 `open_file` 新建一个偏移为零的 `OSInode`，再由 `sys_open` 分配描述符。

两次打开同一文件得到独立偏移。`fork` 克隆描述符表中的 `Arc`，父子进程共享原文件对象及其偏移。`sys_close` 取走表中的引用；其他描述符仍可持有该对象。

[`sys_read` 和 `sys_write`](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/blob/b47c54b5c1f3254518238b0c7450af9c187b4231/os/src/syscall/fs.rs) 检查描述符和读写权限，克隆文件对象后释放任务控制块的借用，再调用文件接口。用户缓冲区按页表映射拆成若干切片；`OSInode` 顺序处理这些切片，按实际传输字节数推进偏移。读取到文件末尾时，只修改返回字节数所覆盖的缓冲区前缀。

`CREATE` 在文件不存在时创建空文件，在文件已经存在时截断它。`TRUNC` 也会截断已有文件。截断保留 inode 编号和目录项，其他打开对象的偏移保持原值。

## 目录与索引节点

[`Inode`](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/blob/b47c54b5c1f3254518238b0c7450af9c187b4231/easy-fs/src/vfs.rs) 保存磁盘 inode 所在的块号、块内偏移，以及文件系统和块设备引用。它通过块缓存读取或修改 `DiskInode`。磁盘 inode 保存大小、类型、链接数和块地址；每次打开的偏移由上层 `OSInode` 保存。

根目录的 inode 编号为 0。目录内容由 32 字节的 `DirEntry` 组成，每项包含 28 字节名字区域和 4 字节 inode 编号。名字最多使用 27 字节，留一个终止字节。目录中的 inode 编号 0 表示空项，查找和列目录会跳过它。本章使用根目录下的单个文件名。

`create` 分配 inode，初始化大小为零、链接数为 1，再写入目录项。`link` 为已有普通文件增加一个名字，两个名字指向同一 inode，`nlink` 增加 1。名字、源文件、目标名字和链接数溢出均在修改前检查。

`unlink` 清空目录项并减少链接数，目录文件的大小保持不变。最后一个链接删除时，数据块、间接索引块和 inode 位图项立即回收；本章接口约定此后不再使用旧文件对象。新文件优先复用目录中的空项。

`fstat` 查询当前 inode 元数据。系统调用先检查整个结果缓冲区的地址范围和用户写权限，再按页复制已初始化的 `Stat`，因此跨页结果不会在检查第二页之前写入第一页。

## 数据块与磁盘布局

[`DiskInode`](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/blob/b47c54b5c1f3254518238b0c7450af9c187b4231/easy-fs/src/layout.rs) 占 128 字节，包含 27 个直接地址、一个一级间接地址和一个二级间接地址。块大小为 512 字节，每个间接块保存 128 个 4 字节地址。

| 文件内逻辑块号 | 地址取得方式 |
| --- | --- |
| 0–26 | `direct[逻辑块号]` |
| 27–154 | 一级间接块中的第 `逻辑块号 − 27` 项 |
| 155–16,538 | 设 `n = 逻辑块号 − 155`，先取二级块第 `n / 128` 项，再取对应一级块第 `n % 128` 项 |

例如偏移 79,360 的逻辑块号为 155，恰好开始使用二级间接索引。索引块保存数据块地址，自身也需要分配磁盘块。`total_blocks` 同时计算数据块和索引块；增长文件时按此数量分配，截断时按同样的布局回收。

本次初始镜像有 32,768 个块，共 16 MiB。块 0 是超级块，之后依次是 1 块 inode 位图、1024 块 inode 区和 8 块数据位图；数据区从块 1034 开始，包含 31,734 块。超级块中的长度决定各区位置，inode 编号再转换成 inode 区内的块号与偏移。

`DiskInode::read_at` 按 512 字节边界划分请求，每段先查块地址，再复制块内字节。用户缓冲区的 4096 字节页边界由系统调用层处理，两种边界分别约束文件访问和内存访问。

## 块缓存与写回

[`BlockCacheManager`](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/blob/b47c54b5c1f3254518238b0c7450af9c187b4231/easy-fs/src/block_cache.rs) 最多保留 16 个缓存块。命中后返回已有 `Arc`，队列位置保持不变。缓存满时，从队首开始寻找强引用计数为 1 的条目，移除后装入新块。计数为 1 表示只有缓存管理器持有它；所有条目都被外部引用时，内核触发 panic。

`get_mut` 设置脏标志，`sync` 把脏块写回设备，缓存析构也调用 `sync`。目录操作、文件写入和截断在结束前调用 `block_cache_sync_all`。因此，修改缓存、同步缓存和设备写入分别对应不同的操作次数。

文件系统锁覆盖目录、位图和 inode 的组合修改。同一个缓存块可能同时容纳目录 inode 与目标 inode，代码先释放一个缓存锁，再访问另一个 inode；调用全局同步之前也释放各块的锁。

文件增长可能依次修改分配位图、索引块、数据块和 inode。这里直接写回各块，没有日志事务。可以结合这个顺序推演突然断电后，哪些块可能已经写回、哪些元数据仍保留旧值。

## 磁盘请求与中断

[`VirtIOBlock`](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/blob/b47c54b5c1f3254518238b0c7450af9c187b4231/os/src/drivers/block/virtio_blk.rs) 实现 `BlockDevice`，把 `read_block` 和 `write_block` 转交给固定版本的 `virtio-drivers`。驱动通过 `0x10001000` 的 MMIO 寄存器与设备通信，提交请求后轮询完成队列。

VirtIO 队列和数据缓冲区通过物理地址供设备访问。`VirtioHal::dma_alloc` 逐页分配并检查物理页连续，把 `FrameTracker` 保存在 `QUEUE_FRAMES` 中；`virt_to_phys` 通过内核页表转换地址。

在调用链中，上层 `VirtIOBlock::read_block` 与驱动内部 `VirtIOBlk::read_block` 是同一请求的两层入口。它们的次数应分别核对，不能相加作为磁盘读取次数。`get_block_cache` 命中时则可以完全省去这条设备路径。

## 程序装载与资源释放

初始进程和 `exec` 从根目录读取程序文件。装载器先 `open_file`，再用 `read_all` 从当前偏移读到文件末尾；新打开对象的偏移为零，所以得到完整 ELF。`MemorySet::from_elf` 按 `PT_LOAD` 段建立映射和权限。

`exec` 替换地址空间及异常上下文，保留进程身份和文件描述符表。`fork` 复制地址空间，同时共享已有文件对象。退出时清空描述符表，释放其中的引用，再回收用户数据页；父进程等待结束后，剩余进程资源随最后一个强引用释放。

关闭描述符与删除目录项分别作用于进程资源和磁盘文件。一次进程退出可以释放文件对象，而磁盘中的程序文件和普通数据文件继续保留。

## 运行观察

基础批次从 shell 执行 `ch6b_usertest`，运行 13 个课程测试；扩展批次执行 `ch6_usertest`，运行 27 个课程测试。两次录制均核对每个测试的开始、退出和预期异常。初始镜像中的 53 个程序文件与参考构建的用户 ELF 逐一相同。

下表统计完整原始流中的函数入口与物理页语义记录。

| 观察点 | 基础测试 | 扩展测试 |
| --- | ---: | ---: |
| `get_block_cache` 入口 | 2,472 | 33,155 |
| 设备读取 | 797 | 10,143 |
| 设备写入 | 7 | 8,509 |
| `create` 入口 | 1 | 14 |
| `link` 入口 | 0 | 3 |
| `unlink` 入口 | 0 | 14 |
| `block_cache_sync_all` 入口 | 2 | 534 |
| 物理页分配 | 1,443 | 2,896 |
| 物理页归还 | 1,333 | 2,786 |
| 分配器使用页数峰值 | 710 | 718 |
| 录制结束时分配器使用页数 | 110 | 110 |

基础测试新增 `filea`，inode 编号为 54，大小为 13 字节，内容为 `Hello, world!`，数据位于磁盘块 3381。扩展测试还留下同样内容的 `fname` 和空文件 `fname1`。两份运行后的镜像中，原有 53 个程序文件的 inode、大小、内容和数据块地址保持不变。扩展测试会删除临时名字，最终目录大小和文件数量因而不能替代创建、删除操作的次数。

扩展批次的 `ch6_file3` 每轮向 `fname3` 写入 `58 × 50 × 50 = 145,000` 字节，关闭后删除，重复 10 轮。这个大小越过 79,360 字节边界，使用二级间接索引。最后目录中没有 `fname3`，完整记录仍保存了分配、写回和回收的过程。

基础报告保留的调用链包括 `Inode::read_at → DiskInode::read_at → get_block_id`。扩展报告还能找到缓存替换时释放 `Arc`，继而调用 `VirtIOBlock::write_block` 的路径。搜索 `get_block_cache`、`clear_inode_data`、`link` 或 `unlink`，可以把文件操作、缓存访问与设备请求联系起来。

[打开基础测试报告](../reports/rcore/ch6/2026a/rcore-2026A-ch6-basic-observed.html) · [打开扩展测试报告](../reports/rcore/ch6/2026a/rcore-2026A-ch6-extended-observed.html)

<details>
<summary>构建与录制参数</summary>

用户程序固定到 [`a059366`](https://github.com/LearningOS/rCore-Tutorial-Test/tree/a0593662ad55d670ba8c27ce1763347cd0dd552f)。观察版使用 `rcore-2026a-ch6-observation.patch`，记录物理页、fork、调度切换和区域解除映射，并保留目录查找入口。用户 ELF 从参考构建复制，镜像生成后逐项核对文件内容。

工具链为 `nightly-2024-05-02`，QEMU 为 10.2.2。内核使用 `LOG=TRACE CARGO_PROFILE_RELEASE_DEBUG=2 cargo build --release --locked` 构建。

录制使用 `--no-build --function-returns --watch-all --profile uniform --snapshots 80 --max-ram-bytes 268435456 --no-render --event-stream never`，两批次分别传入 `--program ch6b_usertest` 和 `--program ch6_usertest`，超时窗口为 360 秒。每批次从同一初始镜像的独立工作副本运行，结束后保存实际磁盘内容。

[基础测试记录](../reports/rcore/ch6/2026a/recording.json)与[扩展测试记录](../reports/rcore/ch6/2026a/rcore-2026A-ch6-extended-observed.json)保存实际构建、录制、分析命令，以及源码、补丁、ELF、前后磁盘镜像、原始轨迹和报告的校验值。

</details>
