# ArceOS 样例

四个应用各有报告和同名 `.evidence.json`：
[tracecomplete](apps/tracecomplete/tracecomplete.html)、
[helloworld](apps/arceos-helloworld/arceos-helloworld.html)、
[lazymapping](apps/arceos-lazymapping/arceos-lazymapping.html)、
[userprivilege](apps/arceos-userprivilege/arceos-userprivilege.html)。

tracecomplete 的 `manifest.json` 和 `console.log` 与报告放在同一目录。
提交的 manifest 隐去了录制机路径；证据中的 manifest 哈希对应归档原件。
tracecomplete 已用完整观察范围和返回指令重新录制，报告保留 149,980 个函数入口；
严格覆盖率为 86.10%，剩余缺项见证据 JSON 的 `coverage.blockers`。
其他三个应用尚未替换，仍以各自证据中的缺项为准。
