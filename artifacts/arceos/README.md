# ArceOS 样例

四个应用各有报告和同名 `.evidence.json`：
[tracecomplete](apps/tracecomplete/tracecomplete.html)、
[helloworld](apps/arceos-helloworld/arceos-helloworld.html)、
[lazymapping](apps/arceos-lazymapping/arceos-lazymapping.html)、
[userprivilege](apps/arceos-userprivilege/arceos-userprivilege.html)。

tracecomplete 的 `manifest.json` 和 `console.log` 与报告放在同一目录。
提交的 manifest 隐去了本机路径；证据中的 manifest 哈希对应归档原件。
这次运行观察了 20 个点，记录到 13 次命中和 49 次限流丢弃；
报告保留 13 个函数入口。各应用当前覆盖缺项见证据 JSON 的 `coverage.blockers`。
