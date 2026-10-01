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

## 源码与调用栈

安装 LLVM，并将 `llvm-symbolizer` 和 `llvm-cxxfilt` 加入 `PATH`。录制时会将 DWARF 引用的内核源码保存到运行目录的 `source.snapshot.zlib`；依赖库位于其他目录时，可重复传入 `--source-root`。

```sh
python -m nodefusion.host.cli record --kernel /path/to/kernel --name boot \
  --source-root /path/to/kernel --source-root /path/to/dependencies
python -m nodefusion.host.cli render --run boot
```

已有记录可以在渲染时补充源码。`--source-map` 将编译时的目录映射到本地目录，`--source-root` 指定允许读取的目录。这些文件会嵌入 HTML，报告离线打开时也能查看。

```sh
python -m nodefusion.host.cli render --run boot \
  --source-root /path/to/kernel \
  --source-map /home/build/kernel=/path/to/kernel
```

在“函数轨迹”中选择入口事件，再选择调用栈中的帧，即可查看对应源码。父帧显示调用位置，当前帧显示入口位置；内联函数的位置通过源码工具栏切换。调用栈支持方向键，分隔条支持拖动和方向键调整。源码支持文件内查找、跳转到行和返回当前位置。

事件详情中的“源码”可直接查看代码，保留当前筛选。进程和物理页详情列出相关事件，查看后可返回原来的资源和时刻。文件描述符表中的进程行也可打开进程详情。

手机上，详情占满屏幕，通过顶部标签切换事件详情、调用栈和源码。“返回列表”始终可见，选择栈帧后直接打开对应代码；Esc 返回列表。
