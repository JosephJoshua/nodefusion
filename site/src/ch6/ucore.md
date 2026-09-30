# uCore 实现

第六章把程序和普通文件放到磁盘上。一次 `read` 从进程的文件描述符出发，经过文件对象、inode、块缓存，最后才可能向 VirtIO 设备发起请求。以下代码来自 [uCore 2026A 第六章](https://github.com/LearningOS/uCore-Tutorial-Code-2026A/tree/df045c4455f2dacb81caf39510aed994bf49ade7)。

## 文件对象与描述符

每个进程有 16 个文件描述符槽，槽中保存指向全局 [`filepool`](https://github.com/LearningOS/uCore-Tutorial-Code-2026A/blob/df045c4455f2dacb81caf39510aed994bf49ade7/os/file.c) 的指针。文件对象保存引用数、读写权限、当前偏移和 inode 指针。两次独立打开同一文件得到两个文件对象，各有自己的偏移；`fork` 则复制指针并增加引用数，父子进程共享偏移。

`inoderead`、`inodewrite` 根据本次传输的字节数推进文件对象中的偏移。`fileclose` 在最后一份引用关闭时释放文件对象对 inode 的引用。文件对象消失不等于磁盘文件被删除。

本章 `sys_read`、`sys_write` 检查描述符是否有效，并根据文件类型进入控制台或 inode 路径；代码尚未用文件对象的 `readable`、`writable` 字段限制这两个调用。`O_TRUNC` 则通过 `itrunc` 清空文件内容并回收块。

## 目录与索引节点

磁盘上的 `dinode` 保存文件类型、大小和块地址；内存中的 `inode` 另有设备号、inode 编号和引用数。`iget` 在内存表中查找或取得一个槽，`ivalid` 首次使用时从磁盘载入，`iupdate` 把改动写回。

根目录的 inode 编号是 1。每个目录项占 16 字节，前 2 字节是 inode 编号，后 14 字节是名字。`dirlookup` 按目录项遍历，`dirlink` 写入空项或追加新项。此时 `namei` 直接在根目录查找文件名，还没有逐级解析路径。

内存 inode 的引用数表示当前有多少内核对象持有它。这个提交没有维护磁盘文件链接数；`linkat`、`unlinkat` 和 `fstat` 系统调用仍返回 -1。阅读 `fileclose → iput` 时，应将引用数变化与磁盘目录项分开。

## 数据块与磁盘布局

文件系统块大小为 1024 字节。一个磁盘 inode 有 12 个直接块地址，以及一个一级间接块地址；间接块可保存 256 个地址。文件内逻辑块号 0–11 直接查 inode，12–267 则在间接块中查找。最大文件长度为 268 个块。

[`bmap`](https://github.com/LearningOS/uCore-Tutorial-Code-2026A/blob/df045c4455f2dacb81caf39510aed994bf49ade7/os/fs.c) 把文件内的逻辑块号转换为磁盘块号，缺块时调用 `balloc`。`writei` 按块写入并更新 inode 的大小和块地址；`readi` 按文件大小截断读取范围，再通过 `bread` 取得相应块。

本次镜像有 1000 个块：块 0 为引导块，块 1 为超级块，块 2–14 存放 inode，块 15 为位图，数据区从块 16 开始。位图管理磁盘块，内存 inode 表则管理当前载入的 inode；两者容量不同。

## 块缓存与写回

[`bcache`](https://github.com/LearningOS/uCore-Tutorial-Code-2026A/blob/df045c4455f2dacb81caf39510aed994bf49ade7/os/bio.c) 有 30 个缓存项。`bget` 先查找相同设备号和块号；未命中时，从链表尾部挑选无人引用的缓存项。`bread` 只在缓存尚无有效内容时读取设备；`bwrite` 把缓存内容写回设备；`brelse` 释放引用并调整链表次序。

目录、位图、inode 和文件数据都经过这套缓存。`itrunc` 依次释放直接数据块、间接数据块与间接索引块，再更新 inode。磁盘写入按块发生，这个文件系统没有日志事务。

## 磁盘请求

[`virtio_disk_rw`](https://github.com/LearningOS/uCore-Tutorial-Code-2026A/blob/df045c4455f2dacb81caf39510aed994bf49ade7/os/virtio_disk.c) 用三个描述符组成一次请求：请求头、数据缓冲区和完成状态。文件系统块为 1024 字节，设备扇区为 512 字节，因此扇区号是文件系统块号的两倍。

驱动将请求放入 available ring，通知设备，然后等待完成。设备中断进入 `virtio_disk_intr`；该函数读取 used ring、检查状态并标记请求完成。由 `bread` 进入驱动的是读请求，由 `bwrite` 进入驱动的是写请求。缓存命中时，`bread` 不会再次访问设备。

## 程序装载与资源释放

[`bin_loader`](https://github.com/LearningOS/uCore-Tutorial-Code-2026A/blob/df045c4455f2dacb81caf39510aed994bf49ade7/os/loader.c) 从磁盘读取平坦二进制文件，从用户地址 `0x1000` 起逐页装入。程序之后留一页未映射空间，再建立用户栈。`exec` 换掉旧用户映射并装入新程序，进程已打开的文件仍在描述符表中。

进程退出时，`freeproc` 释放用户页表并逐个关闭文件。父进程以后从僵尸进程表项取回退出码；磁盘文件不因进程退出而消失。

## 运行观察

课程批次以 `ch6b_usertest` 为初始程序。测试创建文件 `filea`，写入 `Hello, world!` 和换行；运行后磁盘上的文件大小为 14 字节。

在[运行报告](../reports/ucoreos/ch6/2026a/ucore-2026A-ch6-basic-observed.html)中依次查看 `fileopen → readi → bread → virtio_disk_rw`，可以区分文件名查找、文件内偏移、块缓存和设备请求。`virtio_disk_intr` 则对应请求完成。另一条 `sys_exec → exec → namei → dirlookup → readi` 调用链展示了程序如何从磁盘文件变成用户地址空间中的页面。[录制信息](../reports/ucoreos/ch6/2026a/recording.json)保存构建和磁盘镜像记录。
