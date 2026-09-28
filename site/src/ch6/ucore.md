# uCore 实现

源码固定到 [`df045c4`](https://github.com/LearningOS/uCore-Tutorial-Code-2026A/tree/df045c4455f2dacb81caf39510aed994bf49ade7) 的 `ch6-api-impl`。文件对象位于 `os/file.c`，磁盘布局与目录操作位于 `os/fs.c`，缓存和设备驱动分别位于 `os/bio.c` 与 `os/virtio_disk.c`。

## 文件对象与描述符

每个进程的 `files` 数组有 16 个槽，保存指向全局 [`filepool`](https://github.com/LearningOS/uCore-Tutorial-Code-2026A/blob/df045c4455f2dacb81caf39510aed994bf49ade7/os/file.c) 的指针。`struct file` 保存引用数 `ref`、读写权限、偏移 `off` 和 inode 指针。`fileopen` 查找或创建文件，取得空闲文件对象，再由 `fdalloc` 分配描述符。

独立打开同一文件得到两个 `off = 0` 的对象。`fork` 复制文件指针并增加 `ref`，父子进程因而共享原偏移。`inoderead` 与 `inodewrite` 在传输返回值大于零时推进偏移。关闭描述符减少引用数；最后一份引用释放时，`fileclose` 调用 `iput` 并清空文件对象。

[`sys_read` 和 `sys_write`](https://github.com/LearningOS/uCore-Tutorial-Code-2026A/blob/df045c4455f2dacb81caf39510aed994bf49ade7/os/syscall.c) 检查描述符范围和槽是否为空，再按文件类型调用控制台或 inode 读写。本提交在 `fileopen` 中设置 `readable`、`writable`，这两条系统调用路径没有检查它们。可以从这里练习为只读、只写文件补充权限检查。

`O_CREATE` 打开已有普通文件时保留内容。`O_TRUNC` 调用 `itrunc`，清空大小并回收块；原 inode 身份保留，其他打开对象的偏移也保持原值。

## 目录与索引节点

磁盘上的 `dinode` 保存类型、大小和块地址。内存 [`inode`](https://github.com/LearningOS/uCore-Tutorial-Code-2026A/blob/df045c4455f2dacb81caf39510aed994bf49ade7/os/file.h) 还保存设备号、inode 编号、引用数和 `valid` 标志。`iget` 查找或分配内存 inode，`ivalid` 首次使用时从磁盘装入，`iupdate` 把修改过的字段写回磁盘。

根目录 inode 编号为 1。目录项占 16 字节，包含 2 字节 inode 编号和 14 字节名字。`dirlookup` 按目录项大小遍历根目录，`dirlink` 查找空项或追加目录内容。本章的 `namei` 直接在根目录查找传入的名字，没有逐级路径遍历。

内存 inode 引用数与磁盘文件的链接数属于不同概念。此提交的 `inode`、`dinode` 尚未保存链接数，`sys_fstat`、`sys_linkat` 和 `sys_unlinkat` 返回 `-1`。`iput` 中回收磁盘 inode 的分支由常量 0 禁用，实际执行的是减少内存引用数。

`root_dir` 会取得一份根 inode 引用。`create` 在完成查找和目录修改后释放它；`namei` 返回目标 inode 时没有释放这份根目录引用。阅读引用数的变化时，应分别追踪临时目录引用、文件对象引用和打开文件所持有的 inode 引用。

## 数据块与磁盘布局

[`fs.h`](https://github.com/LearningOS/uCore-Tutorial-Code-2026A/blob/df045c4455f2dacb81caf39510aed994bf49ade7/os/fs.h) 定义 1024 字节的块和 64 字节的磁盘 inode。inode 保存 12 个直接地址和一个一级间接地址；间接块保存 256 个 4 字节地址，因此最多寻址 268 个数据块，共 274,432 字节。

| 文件内逻辑块号 | 地址取得方式 |
| --- | --- |
| 0–11 | `addrs[逻辑块号]` |
| 12–267 | `addrs[12]` 指向的间接块中的第 `逻辑块号 − 12` 项 |

[`bmap`](https://github.com/LearningOS/uCore-Tutorial-Code-2026A/blob/df045c4455f2dacb81caf39510aed994bf49ade7/os/fs.c) 返回逻辑块对应的磁盘地址；地址为零时调用 `balloc` 分配块。读取和写入都通过它取得地址。`writei` 检查偏移、整数溢出与最大容量，按块复制用户字节并显式写回，最后调用 `iupdate` 保存大小和块地址。它拒绝从文件末尾之外的偏移开始写入。

本次镜像有 1000 个块。块 0 预留为引导块，超级块位于块 1，13 块 inode 区从块 2 开始，位图位于块 15，数据区从块 16 开始，共 984 块。镜像包含 200 个磁盘 inode；内存 inode 表容量为 50，分别决定磁盘文件容量和同时持有的 inode 数量。

数据位图包含整个磁盘的块号，生成镜像时已标记元数据块。`balloc` 设置空闲位并清零新块，`bfree` 清除对应位。inode 分配则扫描磁盘 inode 的 `type`，以零值表示空闲。

## 块缓存与写回

[`bcache`](https://github.com/LearningOS/uCore-Tutorial-Code-2026A/blob/df045c4455f2dacb81caf39510aed994bf49ade7/os/bio.c) 保存 30 个 `buf`，以双向链表连接。`bget` 先按设备号和块号查找已有条目；没有命中时，从链表尾部寻找 `refcnt = 0` 的条目，重设块号并清除 `valid`。

`bread` 取得缓存后，仅在 `valid = 0` 时读取设备，完成后设置有效标志。`bwrite` 直接发出设备写请求。`brelse` 减少引用数，归零时把条目移到链表前端，使最近释放的块更晚被替换。

位图、目录、数据和 inode 更新都使用同一缓存。`itrunc` 回收直接块及间接块中的数据地址，再回收间接索引块，清空大小并调用 `iupdate`。一次截断因此可能触发多次位图读取和写入。

该实现逐块更新磁盘，没有日志事务层。可以沿 `balloc → bzero → writei → iupdate` 检查新块分配、数据写入和 inode 地址发布的先后关系，再推演更新途中断电的结果。

## 磁盘请求与中断

[`virtio_disk_rw`](https://github.com/LearningOS/uCore-Tutorial-Code-2026A/blob/df045c4455f2dacb81caf39510aed994bf49ade7/os/virtio_disk.c) 为一次请求取得三个描述符，分别指向请求头、1024 字节数据和一个字节的完成状态。VirtIO 块设备使用 512 字节扇区，文件系统块号因此转换为 `sector = blockno × 2`。

驱动把描述符链首写入 available ring，经过内存屏障更新队列索引，再通过 MMIO 通知设备。读取请求允许设备写入数据缓冲区；写入请求则由设备读取该缓冲区。

提交后，驱动打开中断并忙等 `b->disk`。PLIC 转发设备中断，`virtio_disk_intr` 确认中断、读取 used ring 和状态字节，清除 `b->disk`。发起者随后关闭中断，释放描述符链。等待本次设备完成时没有主动调度；取得三个空闲描述符失败的路径则调用 `yield` 后重试。

提交队列、设备传输和中断通知分属不同步骤。检查报告时，可以从 `virtio_disk_rw` 找到请求，从 `virtio_disk_intr` 找到完成处理，再回到 `bread` 或 `bwrite` 的调用者。

## 程序装载与资源释放

[`bin_loader`](https://github.com/LearningOS/uCore-Tutorial-Code-2026A/blob/df045c4455f2dacb81caf39510aed994bf49ade7/os/loader.c) 读取磁盘中的平坦二进制程序，从用户地址 `0x1000` 开始逐页装入，映射权限为 `U | R | W | X`。最后一页超过文件末尾的部分清零；程序之后留出一页未映射区，再建立用户栈。

`exec` 先按名字查找 inode，再解除旧用户映射，调用 `bin_loader` 装入新程序，并把参数压入新用户栈。进程的文件描述符数组保持不变。`fork` 复制用户页，文件对象继续由父子进程共享。

退出时，`freeproc` 释放用户页表，逐槽关闭文件并清空指针。父进程仍可从僵尸记录取得退出码；等待路径取走的是这份退出信息。关闭最后一份文件引用会释放内存对象，而对应磁盘文件继续存在。

## 运行观察

本次内核以 `ch6b_usertest` 为初始程序，课程正向检查包含 14 个测试，覆盖进程、内存、文件读写和参数传递。初始镜像中的 24 个程序文件与参考构建的用户二进制文件逐项相同。

下表使用完整原始流的函数入口与物理页语义记录。设备请求共 138 次，其中 8 次由 `bwrite` 发起，其余 130 次是缓存装入时的读取。

| 观察点 | 次数 |
| --- | ---: |
| `bread` 入口 | 636 |
| `brelse` 入口 | 636 |
| `bwrite` 入口 | 8 |
| `virtio_disk_rw` 入口 | 138 |
| `virtio_disk_intr` 入口 | 138 |
| `readi` 入口 | 469 |
| `writei` 入口 | 2 |
| `fileopen` 入口 | 2 |
| `fileclose` 入口 | 191 |
| `bin_loader` 入口 | 21 |
| 物理页分配 | 635 |
| 物理页归还 | 564 |
| 分配器使用页数峰值 | 127 |
| 录制结束时分配器使用页数 | 71 |

运行结束后，新增 `filea` 的 inode 编号为 26，数据位于磁盘块 192，大小为 14 字节，内容为 `Hello, world!` 加换行。原有 24 个程序文件的内容、inode 和数据块地址保持不变。`writei` 的两次入口分别用于目录项和文件内容；位图、清零和 inode 更新还会经过其他 `bwrite` 路径。

在函数视图中搜索 `fileopen`、`readi`、`bread` 和 `virtio_disk_rw`，分别查看打开文件、逻辑块读取、缓存访问和设备请求。再搜索 `virtio_disk_intr`，结合设备中断事件检查一次请求的完成路径。`inodewrite` 更新文件对象偏移，`iupdate` 更新磁盘 inode，可以通过调用者区分这两个层次。

保留的调用链包含 `sys_exec → exec → namei → dirlookup → readi` 和 `kerneltrap → devintr → virtio_disk_intr`。前者从程序名找到文件字节，后者从内核态设备中断进入完成处理。

[打开本次运行报告](../reports/ucoreos/ch6/2026a/ucore-2026A-ch6-basic-observed.html)

<details>
<summary>构建与录制参数</summary>

用户程序固定到 [`1733f46`](https://github.com/LearningOS/uCore-Tutorial-Test/tree/1733f460c596b013b1c509ad42afa428640783b0)，应用内核自带的 `tools/tests-upstream.patch` 后构建。观察版复制参考构建的实际用户二进制文件，并使用 `ucore-2026a-build.patch` 与 `ucore-2026a-ch6-observation.patch`。前者调整汇编源文件的 Makefile 展开方式，后者记录物理页、fork、调度和页表解除映射。

工具版本为 GCC 14.2.0、CMake 3.31.6、QEMU 10.2.2。内核使用 `make build LOG=info CHAPTER=6 INIT_PROC=ch6b_usertest` 构建。

录制使用 `--no-build --function-returns --watch-all --profile uniform --snapshots 80 --max-ram-bytes 268435456 --timeout 600 --no-render --event-stream never`。运行从初始镜像的独立工作副本开始，测试结束后保存实际磁盘内容。

[录制记录](../reports/ucoreos/ch6/2026a/recording.json)保存实际命令、课程检查、补丁和磁盘文件内容的校验值，以及完整轨迹计数和调用链示例。

</details>
