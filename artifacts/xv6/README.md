# xv6-riscv 样例

新生成的 [lab3-cow 单次报告](lab3-cow/lab3-cowtest-mac.html)及同名
`.evidence.json` 记录来源哈希和严格覆盖缺项。以下三份是更早的独立样例：

| 文件 | 是什么 |
|------|--------|
| [`boot/boot-trace.html`](boot/boot-trace.html) | 从上电到 shell 的启动过程 |
| [`lab3-lazy/lab3-lazy.html`](lab3-lazy/lab3-lazy.html) | lazy allocation 实验，19.2 亿条指令 |
| [`lab3-cow/compare-cow.html`](lab3-cow/compare-cow.html) | 两次运行并排对比：COW 开 vs 关 |

## 这几份跟 rCore / ArceOS 那两份不是同一批

老实说清楚，别让人以为它们是平行的：

* **早于 manifest 机制。** 这三份的 `manifest.json` 里没有 `kernel_kind` 字段 ——
  录它们的时候还没有"每个内核一份 manifest"这套东西，内核细节是写死在代码里的。
* **不是这台机器录的。** `kernel_elf` 指向 `E:\...\xv6-riscv_teacher\kernel\kernel`，
  一台 Windows 机器上的路径。文件按原样保留，没有改写。
* **在本仓库里重录不出来。** xv6 源码树已经从仓库里删掉了（它曾经是唯一一个
  住在仓库内部的内核，其他内核都在外面，这是不对称的）。要重录得自己准备一份
  xv6-riscv 源码，然后 `--kernel` 指过去。

内容本身是真的 —— 就是 NodeFusion 跑 xv6 的输出。只是**版本比另外两个旧**，
看的时候心里有数就行。

## 为什么只留三份

原来 `nodefusion/reports/` 下有 11 份，其中 `lab3-cowtest.html` 单个 16 MB。
留下的这三份覆盖了三种不同的东西（启动 / 单次运行 / 对比），其余的是同类重复。
删掉的那些还在 git 历史里。
