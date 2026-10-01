# 运行报告

- [xv6-riscv](xv6/)
- [rCore](rcore/)
- [ArceOS](arceos/)
- [StarryOS](starryos/)
- [uCoreOS](ucoreos/)

HTML 可以离线打开。事件详情和函数轨迹中可以查看源码。
对应的 JSON 文件记录输入哈希、事件数量和检查结果。
原始 `trace.nfb`、内核 ELF 和源码快照保存在录制归档中。

从归档重新生成报告：

```sh
python -m scripts.regenerate_artifact \
  --run nodefusion/runs/<run-name> \
  --out artifacts/<kernel>/<chapter-or-app>/<run-name>.html \
  --replace
```
