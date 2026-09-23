# 内核侧观测补丁

这些补丁在内核操作完成后写入 `nftrace` 记录。QEMU 插件继续负责指令、寄存器、异常、
函数入口、返回指令和物理内存快照。线格式见
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

章节补丁如下：

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

ch8 使用的 `ucore-nodefusion.patch` 针对 `LearningOS/uCore-Tutorial-Code` 提交
`7728a992c20ce43627fbc319ccb4f5765e807cba`。它提供页分配、释放、进程创建和线程创建
记录，并在 PTE 写入成功后调用 `nodefusion_pagetable_map`。`mappages` 和 `uvmunmap`
保留区域级映射与解除映射事件。

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
