# ArceOS 样例

[`apps/tracecomplete/tracecomplete.html`](apps/tracecomplete/tracecomplete.html) ——
ArceOS 的 `app-childtask`（创建子任务、等它结束）。

## 量出来的

| | |
|---|---|
| 事件 | 34 行，其中 33 条解出了 kind，1 条没有 |
| kind 种类 | 13 |
| 状态快照 | 70 个 |
| 观察点 | 装了 20 个，命中 13 次，**限流丢弃 49 次** |
| 插件计到的指令 | 67 517 556 |
| 异常 / 中断 | 20 次 |
| 内核 ELF | `arceos-55f7257f.elf` |

全部 13 种，一条不省：

```
19  firmware.trap
 3  sched.switch
 2  proc.exit
 1  None            ← 这条没解出 kind
 1  trap.init
 1  heap.init / heap.alloc / heap.free
 1  vm.init / vm.aspace_create / vm.map
 1  proc.create
 1  sbi.call
```

## 这份很薄，原因说清楚

跟 rCore 那份（69 713 条）比差了三个数量级。不是解码器坏了 —— 上面这 13 种
都是解出来的。是**armed 的观察点本来就少**（20 个），而且里面没有 syscall /
page_fault 那几条路径：ArceOS 是 unikernel，应用和内核在同一个地址空间里，
没有 xv6/rCore 那种用户态陷入。所以 `syscall.*`、`trap.page_fault` 这些在
这里一条都不会有，跟"没测到"是两回事。

`limit 丢弃 49 次`那一栏也别忽略：命中 13 次、丢弃 49 次，说明限流阈值对这个
负载偏紧，真实命中比记下来的多。要更全的话得调 `--sample-insns` 一类的参数
重录。

那条 `None` 是一个没能归到任何 kind 的事件，保留原样，没有硬塞进某一类。
