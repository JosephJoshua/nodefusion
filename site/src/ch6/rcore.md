# rCore 实现

第六章把文件接口接入进程的描述符表，并用 easy-fs 在块设备上保存目录和文件。以下代码取自 [2026A 第六章参考实现](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/tree/b47c54b5c1f3254518238b0c7450af9c187b4231)。

## 文件对象与描述符

[`OSInode`](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/blob/b47c54b5c1f3254518238b0c7450af9c187b4231/os/src/fs/inode.rs) 把磁盘 inode 包装为进程可使用的文件对象，保存访问权限和当前偏移。`open_file` 每次成功打开都会创建一个新的 `OSInode`，所以两次打开同一文件有各自的偏移。`fork` 克隆描述符表中的 `Arc`，父子进程则共享原来的文件对象及偏移。

`sys_read` 和 `sys_write` 从描述符表取出文件对象，检查权限，随后调用 `File` 接口。用户缓冲区按页拆分；文件对象根据实际读写的字节数推进偏移。关闭描述符只移除该槽中的引用，其他描述符仍可继续使用同一对象。

## 目录与索引节点

easy-fs 的 [`Inode`](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/blob/b47c54b5c1f3254518238b0c7450af9c187b4231/easy-fs/src/vfs.rs) 根据 inode 所在块号和块内偏移访问磁盘元数据。目录内容由固定大小的 `DirEntry` 构成，每项占 32 字节，保存文件名和 inode 编号。

创建文件时，文件系统分配 inode，并在目录中加入名字。`link` 为已有文件增加目录项和链接数。`unlink` 移除目录项、减少链接数；最后一个链接消失时回收该文件的数据块和 inode。截断文件会清空数据块，目录项和 inode 编号继续保留。

## 数据块与磁盘布局

[`DiskInode`](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/blob/b47c54b5c1f3254518238b0c7450af9c187b4231/easy-fs/src/layout.rs) 保存 27 个直接块地址、一个一级间接块地址和一个二级间接块地址。块大小为 512 字节，间接块可以存放 128 个块地址。

| 文件内的块号 | 查找方式 |
| --- | --- |
| 0–26 | 直接地址 |
| 27–154 | 一级间接块 |
| 155 起 | 二级间接块，再进入对应的一级间接块 |

文件偏移达到 79,360 字节时开始使用二级间接块。索引块本身也占用磁盘块；文件增长时分配，截断时一并回收。`DiskInode::read_at` 以 512 字节块为界处理数据，系统调用层另以 4096 字节页为界处理用户缓冲区。

## 块缓存与写回

[`BlockCacheManager`](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/blob/b47c54b5c1f3254518238b0c7450af9c187b4231/easy-fs/src/block_cache.rs) 最多保存 16 个缓存块。命中时直接返回缓存对象；缓存满时，管理器从队列中寻找没有被外部持有的块并替换。

修改缓存块会把它标为脏块。`sync` 将脏块写回设备，文件写入、截断和目录操作结束时调用全局同步。一次文件操作可能更新位图、索引块、数据块和 inode；沿这些写回位置可以理解磁盘状态如何形成。

## 磁盘请求

[`VirtIOBlock`](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/blob/b47c54b5c1f3254518238b0c7450af9c187b4231/os/src/drivers/block/virtio_blk.rs) 把 `read_block`、`write_block` 转交给 VirtIO 块设备驱动。缓存命中时无需发起设备请求；缓存未命中时，调用链才会到达设备读入。

驱动使用 MMIO 寄存器和 VirtIO 队列提交请求，并轮询完成队列。设备访问的是物理地址，队列和数据缓冲区所需的地址由内核的地址转换与页分配接口提供。

## 程序装载与资源释放

初始进程和 `exec` 从文件系统读取 ELF。新打开的 `OSInode` 偏移为零，`read_all` 从文件开头读到结尾；`MemorySet::from_elf` 再建立程序的用户映射。

`fork` 复制地址空间并共享已有文件对象。`exec` 替换地址空间，保留描述符表。进程退出时清空描述符表，用户数据页也随退出路径回收。

## 运行观察

报告可从 `Inode::read_at` 沿 `DiskInode::read_at → get_block_id` 追到文件内块号的查找。再选择 `get_block_cache`，可以区分缓存命中与到达 `VirtIOBlock::read_block` 的请求。

扩展测试中的 `ch6_file3` 每轮写入 145,000 字节，越过二级间接块的起点；关闭并删除文件后，目录中不再保留 `fname3`。这段运行适合连贯查看数据块分配、缓存写回和文件删除。

[基础测试报告](../reports/rcore/ch6/2026a/rcore-2026A-ch6-basic-observed.html) · [扩展测试报告](../reports/rcore/ch6/2026a/rcore-2026A-ch6-extended-observed.html) · [录制数据](../reports/rcore/ch6/2026a/recording.json)
