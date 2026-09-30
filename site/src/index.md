# 操作系统内核分析

本书使用 rCore 与 uCore 的 2026A 参考实现，分析内核从启动到线程同步的主要机制。源码链接固定到各章对应的提交；运行报告可用于查看函数调用和系统事件。

## 章节

<div class="chapter-index" role="list">
  <div class="chapter-index-row" role="listitem"><span class="chapter-number">01</span><div class="chapter-summary"><a href="ch1/index.html">启动与基本执行环境</a><p>入口汇编设置启动栈，内核初始化 BSS、输出字符并关机。</p></div><div class="chapter-actions"><a href="ch1/rcore.html">rCore</a><a href="ch1/ucore.html">uCore</a><a href="reports.html?chapter=1">运行报告</a></div></div>
  <div class="chapter-index-row" role="listitem"><span class="chapter-number">02</span><div class="chapter-summary"><a href="ch2/index.html">批处理与系统调用</a><p>用户程序通过 <code>ecall</code> 进入内核；异常上下文保存返回位置。</p></div><div class="chapter-actions"><a href="ch2/rcore.html">rCore</a><a href="ch2/ucore.html">uCore</a><a href="reports.html?chapter=2">运行报告</a></div></div>
  <div class="chapter-index-row" role="listitem"><span class="chapter-number">03</span><div class="chapter-summary"><a href="ch3/index.html">多任务与分时调度</a><p>任务上下文让程序暂停后恢复，时钟中断触发抢占。</p></div><div class="chapter-actions"><a href="ch3/rcore.html">rCore</a><a href="ch3/ucore.html">uCore</a><a href="reports.html?chapter=3">运行报告</a></div></div>
  <div class="chapter-index-row" role="listitem"><span class="chapter-number">04</span><div class="chapter-summary"><a href="ch4/index.html">地址空间与页表</a><p>页表完成地址转换，内核检查用户缓冲区的映射和权限。</p></div><div class="chapter-actions"><a href="ch4/rcore.html">rCore</a><a href="ch4/ucore.html">uCore</a><a href="reports.html?chapter=4">运行报告</a></div></div>
  <div class="chapter-index-row" role="listitem"><span class="chapter-number">05</span><div class="chapter-summary"><a href="ch5/index.html">进程</a><p><code>fork</code>、<code>exec</code> 和 <code>wait</code> 连接进程创建、程序替换与资源回收。</p></div><div class="chapter-actions"><a href="ch5/rcore.html">rCore</a><a href="ch5/ucore.html">uCore</a><a href="reports.html?chapter=5">运行报告</a></div></div>
  <div class="chapter-index-row" role="listitem"><span class="chapter-number">06</span><div class="chapter-summary"><a href="ch6/index.html">文件系统</a><p>文件描述符、文件对象、索引节点和磁盘块组成访问路径。</p></div><div class="chapter-actions"><a href="ch6/rcore.html">rCore</a><a href="ch6/ucore.html">uCore</a><a href="reports.html?chapter=6">运行报告</a></div></div>
  <div class="chapter-index-row" role="listitem"><span class="chapter-number">07</span><div class="chapter-summary"><a href="ch7/index.html">进程间通信</a><p>管道传递字节；端点引用决定读写结束与资源回收。</p></div><div class="chapter-actions"><a href="ch7/rcore.html">rCore</a><a href="ch7/ucore.html">uCore</a><a href="reports.html?chapter=7">运行报告</a></div></div>
  <div class="chapter-index-row" role="listitem"><span class="chapter-number">08</span><div class="chapter-summary"><a href="ch8/index.html">线程与同步</a><p>线程共享进程资源；互斥锁、信号量和条件变量协调执行。</p></div><div class="chapter-actions"><a href="ch8/rcore.html">rCore</a><a href="ch8/ucore.html">uCore</a><a href="reports.html?chapter=8">运行报告</a></div></div>
</div>

[报告目录](reports.html)还收录 xv6-riscv、ArceOS 和 StarryOS 的运行记录。

使用 NodeFusion 分析其他内核时，可参考[添加内核支持](guides/adding-kernel.md)和[Manifest 语法参考](guides/manifest-reference.md)。
