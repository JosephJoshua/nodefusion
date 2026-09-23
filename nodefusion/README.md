# 源码目录

从仓库根目录运行 `python -m nodefusion.host.cli`。构建和录制命令见[项目首页](../README.md)。

| 路径 | 内容 |
| --- | --- |
| `plugin/` | QEMU TCG 插件，写入 `trace.nfb` |
| `host/record.py` | 构建内核并启动 QEMU |
| `host/nftrace.py` | 读取二进制轨迹 |
| `host/analyze.py` | 生成事件、状态和指标 |
| `host/bundle.py`、`host/render.py` | 生成 HTML 报告 |
| `model/` | 解析 manifest 和 DWARF，读取内核对象 |
| `manifests/` | 各内核的 TOML 描述 |
| `integrations/` | 内核侧 `nftrace` 补丁 |
| `tests/` | 测试 |

轨迹格式见[事件流规范](spec/event-stream.md)。新增内核见[Manifest 编写指南](../docs/manifests/AUTHORING.md)。
