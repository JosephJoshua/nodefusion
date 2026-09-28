# 教学网站

[在线阅读](https://josephjoshua.github.io/nodefusion/)

正文位于 `src/`，阅读导航与筛选位于 `theme/`。机制交互图位于 `src/diagrams/`。运行报告从仓库的 `artifacts/` 复制到构建结果的 `reports/`。

使用 Python 3.11 及以上版本和 mdBook 0.5.4 构建：

```sh
cargo install mdbook --version 0.5.4 --locked
python scripts/build_education_site.py
python -m http.server 8768 --bind 127.0.0.1 --directory site/book
```

打开 <http://127.0.0.1:8768/>。构建脚本检查页面链接、锚点、SVG、报告内嵌数据和 JSON，并生成包含报告校验和的 `reports/index.json`。`--dest-dir` 可以指定输出目录，`--mdbook` 可以指定 mdBook 可执行文件。

```sh
python -m pytest site/tests -q
node site/tests/switch.test.cjs
node site/tests/blocks.test.cjs
node site/tests/pipe.test.cjs
```

章节页支持逐节阅读、两套实现对照和页内报告。宽屏报告可切换左右并排与上下分屏，窄屏使用全屏报告。返回正文时保留阅读位置和报告筛选条件。

浏览器检查包括目录、筛选、逐节阅读、阅读位置、报告布局和两套实现对照。启动上面的本地服务后，可用 Playwright CLI 执行：

```sh
playwright-cli --session education open http://127.0.0.1:8768/
for suite in navigation sections study comparison ch2 ch4 ch5 ch6 ch7 ch8 \
             pipe report-context report-filters report-layout; do
    playwright-cli --session education goto http://127.0.0.1:8768/
    playwright-cli --session education run-code --filename "site/tests/$suite.browser.js"
done
```

构建结果不提交到 Git。`main` 分支更新站点、报告或构建脚本后，`.github/workflows/education-site.yml` 构建并发布 GitHub Pages；在仓库的 Pages 设置中将发布来源设为 GitHub Actions。站点使用 `/nodefusion/` 路径。新增章节时，同时更新 `src/SUMMARY.md` 和报告目录，保留实现分析、运行观察与练习之间的直接入口。
