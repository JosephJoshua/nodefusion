# 内核侧观测补丁

观测补丁提供 `nftrace` 语义记录或独立的函数入口，目录中还包含各章的构建兼容补丁。
QEMU 插件负责指令、寄存器、异常、函数入口、返回指令和物理内存快照。线格式见
[`spec/event-stream.md`](../spec/event-stream.md)。

补丁应先在目标源码提交上执行 `git apply --check`，再应用和构建。录制完成后检查
`watchlist.json` 与严格审计结果。

## StarryOS

`starry-nodefusion.patch` 和 `starry-cache-trace.patch` 针对 `tgoskits` 提交
`7c5bbd1`。

```sh
git apply --unidiff-zero --check /path/to/nodefusion/nodefusion/integrations/starry-nodefusion.patch
git apply --unidiff-zero /path/to/nodefusion/nodefusion/integrations/starry-nodefusion.patch
git apply --unidiff-zero --check /path/to/nodefusion/nodefusion/integrations/starry-cache-trace.patch
git apply --unidiff-zero /path/to/nodefusion/nodefusion/integrations/starry-cache-trace.patch

CARGO_PROFILE_RELEASE_DEBUG=2 cargo xtask starry build \
  --config os/StarryOS/configs/board/qemu-riscv64.toml
```

QEMU RISC-V board 启用 `starryos/nodefusion-trace` 后提供以下记录：

| 记录 | 内容 |
| --- | --- |
| `NFT_KALLOC` | 分配结果、页数和操作后的页计数 |
| `NFT_KFREE` | 释放起始地址、页数和操作后的页计数 |
| `NFT_ALLOCATOR_STATE` | 字节堆改变页后端占用后的页计数 |
| `NFT_PROC_FORK` | clone/clone3 成功创建的进程 |
| `NFT_THREAD_CREATE` | clone/clone3 成功创建的线程 |
| `NFT_SCHED_SWITCH` | 切出与切入的调度实体 ID 和 Linux TID |
| `NFT_CACHE_READ` | 每次缓存或直读请求的命中、未命中或失败结果 |

分配记录在分配器锁释放后发出。clone 记录在任务成功创建并加入调度后发出。缓存记录按
请求计数，设备层合并相邻读取不会改变命中数。分析器核对缓存结果数与缓存读取入口数后
计算命中率。

构建时使用上面的 board config。`--arch riscv64` 可能复用已有的生成配置，无法保证其中
包含新加入的 feature。

[`starry-thread-probe.S`](starry-thread-probe.S) 是 `CLONE_THREAD` 路径的无 libc
RISC-V 探针。构建命令写在文件头。普通 shell 子进程产生 `NFT_PROC_FORK`，该探针产生
`NFT_THREAD_CREATE`。

## rCore

2026A `ch1-api-impl` 提交 `ebb82caa6bec05652a041e613c12a52fde3813f0` 使用
`rcore-2026a-ch1-observation.patch`，为 `clear_bss` 保留独立入口。

2026A `ch3-api-impl` 提交 `5deb0f963bf27299a3e8e069b95ea684b781e66e` 使用
`rcore-2026a-ch3-observation.patch`，为暂停函数保留独立入口。

2026A `ch4-api-impl` 提交 `ef2dfc4c23c70a1eb4c6a0b30feb694b2d09a73d` 使用
`rcore-2026a-ch4-observation.patch`。页分配器初始化后记录初始页计数，分配和释放
完成后记录物理地址及更新后的计数。完整区域匹配成功后，
`remove_framed_area` 在清除映射前上报起止 VPN。堆操作委托给原有分配器，
保留独立入口；页表创建、映射、区域插入和任务暂停也保留独立入口。

2026A `ch5-api-impl` 提交 `023a5a0885fed8ae999406f17a494777c3e59af1` 使用
`rcore-2026a-ch5-observation.patch`。分配和释放记录包含操作后的页计数；成功的
`fork` 在子进程加入就绪队列后记录双方 PID。调度记录区分进程和 idle 上下文，
idle 使用协议的 no-task 值。区域取消映射、堆缩小和失败映射回滚在清除 PTE 前
记录实际范围。退出时的 `recycle_data_pages` 释放数据页，僵尸进程的页表仍保留，
该路径不产生清除 PTE 的区域事件。堆操作仍委托给原有分配器。

2026A `ch6-api-impl` 提交 `b47c54b5c1f3254518238b0c7450af9c187b4231` 使用
`rcore-2026a-ch6-observation.patch`。它提供相同的页计数、父子 PID 和调度记录，
并为内存区域操作与 `find_inode_id` 保留独立入口。文件系统目录查找和读写算法保持原样。
构建观察版时复用参考构建的用户 ELF 和初始磁盘镜像，再核对每个文件的字节数与校验和。

2026A `ch7-api-impl` 提交 `c8e0313a55ed5926123d990f196061978c460aed` 使用
`rcore-2026a-ch7-observation.patch`。它保留管道缓冲区读写、容量检查、写端关闭检查和
信号处理函数的入口，沿用页计数、父子 PID、调度和区域取消映射记录。管道与信号处理算法保持原样。

2026A `ch8-api-impl` 提交 `00b2a84360710640fbde595c194a7f2447e755f2` 使用
`rcore-2026a-ch8-observation.patch`。成功的 `fork` 记录父子 PID，`thread_create`
完成线程初始化后记录父子 TID。调度记录包含线程对象地址及所属进程 PID；idle 使用
no-task 值。互斥锁、信号量、条件变量和资源回收函数保留独立入口，同步算法保持原样。
区域事件覆盖 `MapArea::unmap` 和缩小区域的路径。`recycle_data_pages` 释放数据页，
僵尸进程仍保留页表项，释放结果由物理页记录表示。

既有章节使用的补丁如下：

| 章节 | 补丁 |
| --- | --- |
| ch3 | `rcore-sched-yield-observation.patch` |
| ch4 | `rcore-ch4-nodefusion.patch`、`rcore-sched-yield-observation.patch`、`rcore-page-table-new-observation.patch`、`rcore-heap-observation.patch` |
| ch5 | `rcore-ch6-nodefusion.patch`、`rcore-page-table-new-observation.patch`、`rcore-heap-observation.patch`、`rcore-ch5-drop-observation.patch` |
| ch6 | `rcore-ch6-nodefusion.patch`、`rcore-page-table-new-observation.patch` |
| ch7 | `rcore-nodefusion.patch`、`rcore-page-table-observation-points.patch` |
| ch8 | `rcore-ch8-nodefusion.patch`，随后应用 `rcore-page-table-observation-points.patch` |

`rcore-nodefusion.patch` 针对 Tutorial ch7 提交 `6eed34d`。它在每个 `MapArea`
移除前上报区域起止 VPN，并覆盖进程退出时的 `areas.clear()` 路径。

各章语义补丁在页帧操作完成并释放分配器借用后发送 `NFT_KALLOC` 或 `NFT_KFREE`，
同时记录精确页计数。两条 `__switch` 路径发送 `NFT_SCHED_SWITCH`；调度器上下文使用协议
定义的 no-task 值。

`rcore-heap-observation.patch` 为 ch4、ch5 的全局分配器提供稳定入口。manifest 在这两个
构建中选择该入口，并跳过同一次操作的 `__rust_*` 包装层。`rcore-page-table-new-observation.patch`
保留 ch4–ch6 的 `PageTable::new` 入口；ch7、ch8 使用覆盖更多页表方法的补丁。

```sh
git apply --unidiff-zero --check /path/to/nodefusion/nodefusion/integrations/rcore-nodefusion.patch
git apply --unidiff-zero /path/to/nodefusion/nodefusion/integrations/rcore-nodefusion.patch
cd os && CARGO_PROFILE_RELEASE_DEBUG=2 make build
```

ch7、ch8 的页表观察点补丁为 `PageTable::new`、`find_pte_create`、`find_pte`、
`map`、`translate` 和 `current_add_signal` 添加 `#[inline(never)]`，使优化构建保留可解析
入口。`rcore-ch8-modern-toolchain.patch` 适配当前 Rust nightly 的 `PanicInfo::message()`
接口。

从不带 Git 分支元数据的 rCore 源码目录构建时，向 `record` 传入 `--make-var CHAPTER=N`
和 `--make-var TEST=N`。ch6 的 `ch6_usertest` 还需 `--make-var BASE=2`，使文件系统镜像
同时包含 `ch6b_initproc`。

easy-fs 没有日志或事务层。rCore manifest 将 `log.commit` 声明为 feature absence。

## uCoreOS

2026A 第二章提交 `729e1ad1632bb639dfe546f34765c0537b503990` 的调用者向
`usertrapret` 传入 `boot_stack_top`，函数再次加上 `PGSIZE`，使异常栈落入
`trap_page`。装载下一个应用时，`memset(trap_page, 0, 4096)` 会清零正在使用的栈。
`ucore-2026a-ch2-stack.patch` 将异常栈指针直接设为传入的栈顶。这是用于比较运行的
机制修正补丁；原参考构建及其停滞轨迹单独保留。

2026A `ch3-api-impl` 提交 `6bb0c2e8d84eda0451092f24f907ed084299e6e6` 使用
`ucore-2026a-build.patch`，固定汇编源文件列表的求值时机，避免生成 `link_app.S` 后
重复链接对应对象。用户程序按课程的 `tools/run_lab.py --mode positive` 构建与检查。

ch8 使用的 `ucore-nodefusion.patch` 针对 `LearningOS/uCore-Tutorial-Code` 提交
`7728a992c20ce43627fbc319ccb4f5765e807cba`。它提供页分配、释放、进程创建和线程创建
记录，并在 PTE 写入成功后调用 `nodefusion_pagetable_map`。`mappages` 和 `uvmunmap`
保留区域级映射与解除映射事件。

2026A `ch4-api-impl` 提交 `51f02268653c68f169f5599055da3b0391995ee6` 使用
`ucore-2026a-ch4-observation.patch`，与 `ucore-2026a-build.patch` 配合构建。
物理页初始化完成后发送初始空闲页计数；分配和释放完成后记录物理地址及更新后的
空闲、已分配页数。分配失败记录地址零。PTE 写入成功后调用
`nodefusion_pagetable_map`，记录虚拟地址、物理地址和权限。

2026A `ch5-api-impl` 提交 `386f10c55d0285273b78df19c4607c0f475e17a2` 使用
`ucore-2026a-ch5-observation.patch`，先应用 `ucore-2026a-build.patch`。
初始化、分配和释放记录空闲与已用页数；`fork` 完成子进程初始化并加入就绪队列后
记录父子 PID。两条 `swtch` 路径记录进程与 idle 的切换，PTE 写入后记录单页映射。

2026A `ch6-api-impl` 提交 `df045c4455f2dacb81caf39510aed994bf49ade7` 使用
`ucore-2026a-ch6-observation.patch`，先应用 `ucore-2026a-build.patch`。
观测位置覆盖物理页分配与释放、成功的 `fork`、调度切换和 PTE 写入。
用户程序使用参考构建的二进制文件，磁盘镜像也从同一初始副本复制。

该观测补丁也适用于 2026A `ch7-api-impl` 提交
`c6f384219f334280fd6a4acad2a58ad2222a9d25`。管道分配、关闭、读写和复制函数已有独立入口。

2026A `ch8-api-impl` 提交 `9d4fa96b67b449bc72f6530286b5a438e9de3ce5` 使用
`ucore-2026a-ch8-observation.patch`，先应用 `ucore-2026a-build.patch`。
成功的 `fork` 记录父子 PID，线程创建记录当前进程内的父子 TID。调度记录使用线程
对象地址和进程 PID。物理页计数与 PTE 写入记录沿用前章格式，线程和同步实现保持原样。

`ucore-2026a-ch4-pagetable-experiment.patch` 在初始化内核页表之后运行独立实验：
建立临时用户页表，映射自有物理页到 `0x4000`，查询页内偏移，再分别用
`do_free=0` 和 `do_free=1` 解除映射。结束时移除 trampoline 映射并回收页表。
它与上面的观测补丁配合使用，实验结束后继续运行原有用户批次。

```sh
git apply --check /path/to/nodefusion/nodefusion/integrations/ucore-nodefusion.patch
git apply /path/to/nodefusion/nodefusion/integrations/ucore-nodefusion.patch
```

ch4–ch7 使用章节对应补丁：

| 章节 | 补丁 |
| --- | --- |
| ch4 | `ucore-legacy-nodefusion.patch` |
| ch5 | `ucore-ch5-nodefusion.patch` |
| ch6、ch7 | `ucore-ch6-ch7-nodefusion.patch` |

ch8 showcase 还使用：

- `ucore-ch8-showcase.patch`：补上自旋互斥锁等待成功后的 `locked = 1`；
- `ucore-user-modern-toolchain.patch`：针对 Tutorial Test 提交
  `1733f460c596b013b1c509ad42afa428640783b0`，启用 Zicsr 并修正测试列表。

`ucore.toml` 使用 QEMU 内置 OpenSBI；仓库内的历史 RustSBI 镜像无法在 QEMU 10.2.2
上完成该构建的启动。uCoreOS 没有日志或事务层，`log.commit` 记为 feature absence。
