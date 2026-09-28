# rCore 实现

参考实现固定到课程仓库提交 [`ebb82ca`](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/tree/ebb82caa6bec05652a041e613c12a52fde3813f0)。本章主函数完成清零、日志初始化、数组求和与输出，最后通过 QEMU 退出设备结束运行。

## 入口与启动栈

[`entry.asm`](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/blob/ebb82caa6bec05652a041e613c12a52fde3813f0/os/src/entry.asm) 在 `_start` 中依次执行 `la sp, boot_stack_top` 与 `call rust_main`。启动栈预留 `4096 × 16` 字节，共 64 KiB。

[`linker.ld`](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/blob/ebb82caa6bec05652a041e613c12a52fde3813f0/os/src/linker.ld) 将代码入口放在 `0x80200000`，随后依次安排只读数据、可写数据和 BSS。各段边界按 4 KiB 对齐。`.bss.stack` 排在 `sbss` 之前。

## 清零与主函数

[`main.rs`](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/blob/ebb82caa6bec05652a041e613c12a52fde3813f0/os/src/main.rs) 使用 `#![no_std]` 和 `#![no_main]`。入口由汇编定义，格式化输出使用核心库和项目中的 SBI 封装。

`clear_bss` 逐字节清零 `[sbss, ebss)`，每次写入使用 `write_volatile`。`rust_main` 先调用它，再执行 `logging::init()`，随后输出问候信息和数组 `[1, 2, 3, 4, 5]` 的求和结果。

日志依次打印代码、只读数据、可写数据、启动栈和 BSS 边界，级别分别为 trace、debug、info、warn、error。本次构建使用 `LOG=TRACE`，五组边界均参与输出。

## 输出与终止

控制台将格式化字符传给 SBI 输出接口。主函数末尾的 [`QEMU_EXIT_HANDLE.exit_success()`](https://github.com/LearningOS/rCore-Tutorial-Code-2026A/blob/ebb82caa6bec05652a041e613c12a52fde3813f0/os/src/boards/qemu.rs) 则向 `0x100000` 的测试设备写入成功退出值。主函数返回类型为 `!`，执行不会返回入口汇编。

## 运行观察

记录 `rcore-2026A-ch1-verified` 使用与参考实现相同的逻辑，仅为 `clear_bss` 增加 `#[inline(never)]`，以保留独立函数入口。未加此属性的参考构建及其原始记录另行保留。

本次 ELF 的布局如下：

| 区域 | 地址区间 |
| --- | --- |
| 代码 | `[0x80200000, 0x80202000)` |
| 只读数据 | `[0x80202000, 0x80203000)` |
| 可写数据 | `[0x80203000, 0x80204000)` |
| 启动栈 | `[0x80204000, 0x80214000)` |
| 清零区间 | `[0x80214000, 0x80215000)` |

主函数入口位于累计第 10,762,845 条指令，记录中的 `sp` 为 `0x80214000`，恰好等于启动栈顶。第 10,762,858 条指令处进入 `clear_bss`，此时 `sp` 为 `0x80213e80`。两次入口之间，主函数已为自身调用帧调整栈指针，减少 384 字节。

清零区间长 4 KiB，与 64 KiB 启动栈相邻。结合链接脚本可以确认，清零起点已经越过整个启动栈。源码中的数组求和还需结合编译结果分析：优化构建允许编译器提前计算结果，源代码中的数组表达式本身不能说明运行时一定存在同样的栈上数组。

本次记录执行 10,923,367 条指令，保存 10 份快照和 172 条函数入口事件。录制结果为 `qemu_exited`，与成功退出设备终止虚拟机的路径一致。函数入口事件在派生报告中全部保留。

[打开本次运行报告](../reports/rcore/ch1/2026a/rcore-2026A-ch1-verified.html)。在函数调用视图中查找 `rust_main` 和 `clear_bss`，再对照本节的入口栈指针与调用顺序。

<details>
<summary>构建与录制参数</summary>

构建在参考仓库的 `os/` 中执行 `LOG=TRACE cargo build --offline --release`，随后用 `rust-objcopy` 生成裸二进制。仓库的工具链配置选择 Rust 1.80 nightly。`Cargo.lock`、ELF 与运行映像的校验和记录在[录制信息](../reports/rcore/ch1/2026a/recording.json)中。

两套第一章报告使用 QEMU 10.2.2、内置 OpenSBI、128 MiB 内存、单核和 `-icount shift=3`。以下命令中的路径变量分别指向参考内核和运行目录：

```sh
python -m nodefusion.host.cli record \
  --kernel "$KERNEL_DIR" --kernel-kind rcore \
  --runs "$RUNS_DIR" --name rcore-2026A-ch1-verified \
  --no-build --function-returns --watch-all --profile uniform \
  --snapshots 80 --max-ram-bytes 268435456 --timeout 90 \
  --no-render --event-stream never
```

报告通过 `python -m scripts.regenerate_artifact --run "$RUN_DIR" --out "$REPORT_HTML" --strict` 生成。录制信息保存实际执行的完整命令、工具源码补丁、构建参数、原始轨迹校验和与启动观察数据。

</details>

## 源码阅读练习

1. 入口的 `call rust_main` 如何影响 `ra`？主函数正常结束时为什么不使用它返回？
2. 若把 `sbss` 移到 `.bss.stack` 之前，清零函数会覆盖哪些正在使用的数据？
3. 将 `LOG=TRACE` 改为 `LOG=INFO` 后，哪些边界消息还会输出？清零操作是否改变？
4. 解释 `write_volatile` 与循环区间边界各自保证了什么。
