# rCore 样例

各章新报告及同名 `.evidence.json`：
[ch1](ch1/rcore-ch1-bare.html)、[ch2](ch2/rcore-ch2-batch.html)、
[ch3](ch3/rcore-ch3-sched.html)、[ch4](ch4/rcore-ch4-exact.html)、
[ch5](ch5/rcore-ch5-exact.html)、[ch6](ch6/rcore-ch6-usertest.html)、
[ch7](ch7/rcore-ch7-100pct-final.html)、
[ch8](ch8/rcore-ch8-exact-filetest.html)。ch7 的严格覆盖检查通过；
其他章的旧录制存在缺项，见相应证据中的 `coverage.blockers`。

以下是更早的 ch6 文件系统与 panic 样例：

两趟：一趟正常跑完，一趟内核崩了。

| 样例 | 跑的什么 | 结局 |
|---|---|---|
| [`ch6/fs-alloc/fs-alloc.html`](ch6/fs-alloc/fs-alloc.html) | ch6 文件系统，`ch6b_filetest_simple` | completed |
| [`ch6/panic/panic.html`](ch6/panic/panic.html) | ch6，`ch6b_nfpanic`（故意打崩内核） | **panic** |

## fs-alloc：量出来的

| | |
|---|---|
| 事件 | 69 713 条，79 种 kind |
| 状态快照 | 45 个 |
| 观察点 | 装了 108 个，命中 63 545 次，限流丢弃 0 |
| 插件计到的指令 | 34 799 712 |
| 异常 / 中断 | 6 168 次 |
| 内核 ELF | `rcore-57942a68.elf` |

最热的几种 kind：

```
32333  pagetable.map
 3311  sbi.call
 2838  trap.userret / trap.enter
 2834  syscall.enter / syscall.dispatch
 2808  vm.translate_buffer
 2572  bcache.read
```

79 种里包含 `func.*` 那一类 —— 那是 manifest 里点名要看的具体函数（比如
`func.Stdin::readable`、`func.virt_to_phys`），不是通用语义事件。

## panic：内核崩了也照样有报告

| | |
|---|---|
| 事件 | 36 167 条，56 种 kind |
| 状态快照 | 22 个 |
| 观察点 | 命中 35 159 次，限流丢弃 0 |
| 插件计到的指令 | 27 650 815 |
| 异常 / 中断 | 1 008 次 |
| `manifest.json` 的 outcome | `panic`（不是 `completed`） |

崩溃点在 console.log 里：

```
[kernel] Panicked at src/syscall/mod.rs:82 Unsupported syscall_id: 9999
```

这一趟是**故意**崩的，而且没有改内核。用户程序 `ch6b_nfpanic` 直接 `ecall`
一个内核不认识的调用号，内核 `syscall/mod.rs` 的 match 兜底那条就是
`panic!("Unsupported syscall_id: {}", syscall_id)`。

为什么要专门造一趟：观测器跑在 QEMU 进程里、在被观察内核之外，所以内核崩了
记录也不会停 —— 但这话得有一趟真崩过的运行来证。报告里能回看崩溃前最后执行
的 PC、函数、异常和内存状态。

（先试过更省事的办法：往 fd 0 写。`Stdin::write` 的函数体确实就是 `panic!`，
但 `sys_write` 会先查 `file.writable()`，Stdin 返回 false，直接 -1 就回来了，
那条 panic 够不着。）

## 怎么来的

ch6 是有 shell 的（串口上的 `>>` 提示符），`--program` 指定跑哪个应用，录制器
把命令写进 guest 的 stdin。两趟都用了 `--no-build`：直接拿现成的二进制，没有
重新编译 —— manifest 里的 `record_warnings` 写明了这点，以及"没人验证过这份
二进制是当前源码编出来的"。ELF 指纹在 `kernel_elf_identity` 里，两趟同一个
内核（`57942a68b4cae1b7`）。

`ch6b_nfprobe` / `ch6b_nfpanic` 这两个探针程序是加在 rCore 那棵树的
`user/src/bin/` 下的，**只重打 fs.img，不碰内核**：打包前后对 os 二进制做过
sha256 比对，逐字节一致（`os/build.rs` 只发 rerun-if-changed，不生成
link_app.S；`fs-img` 规则也不编译 os）。

## kind 覆盖率

manifest 声明了 66 种 kind，本机 25 趟 rCore 录制合起来响过 **62 种**。
没响的 4 种，以及为什么：

| kind | 情况 |
|---|---|
| `inode.alloc` | 调用路径**确实走到了**（量过：fs.img 根目录项 0→1），但观察点没响，原因未查明。详见 `manifests/rcore.toml` 里那段注释，排除过的解释都列在那儿。 |
| `trap.kernel` | 要内核态自己触发异常。用户程序传坏指针进系统调用不行 —— rCore 的地址翻译是手动走页表 + `.unwrap()`，会先 panic，走不到 `trap_from_kernel`。 |
| `kernel.alloc_error` / `panic.alloc_handler` | 要把内核堆耗干。没找到不改内核就能稳定打到的办法。 |

这 4 个都是**没打到**，不是"打到了但工具没记"—— 除了 `inode.alloc`，那个恰恰
相反，所以单独说明。

（这些录制结果本身不进 git：`nodefusion/runs/` 是 gitignore 的，只有上面两趟
被挑出来放进 `artifacts/rcore/`。）
