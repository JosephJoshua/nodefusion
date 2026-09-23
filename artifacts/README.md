# 运行报告

- [xv6-riscv](xv6/)
- [rCore](rcore/)
- [ArceOS](arceos/)
- [StarryOS](starryos/)
- [uCoreOS](ucoreos/)

HTML 可以离线打开。对应的 `.evidence.json`、视频 JSON 或 `coverage.json` 记录输入哈希、
事件数量和审计结果。原始 `trace.nfb` 与内核 ELF 保存在录制归档中。

从归档重新生成报告：

```sh
python -m scripts.regenerate_artifact \
  --run nodefusion/runs/<run-name> \
  --out artifacts/<kernel>/<chapter-or-app>/<run-name>.html \
  --replace
```
