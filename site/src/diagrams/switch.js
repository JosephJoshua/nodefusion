(function (root) {
  'use strict';

  function stepsFor(kernel, scenario) {
    if (!['rcore', 'ucore'].includes(kernel) || !['yield', 'timer', 'exit', 'alone'].includes(scenario)) {
      throw new RangeError('Unknown kernel or scenario');
    }
    const alone = scenario === 'alone';
    const exiting = scenario === 'exit';
    const timer = scenario === 'timer';
    const ready = kernel === 'rcore' ? 'Ready' : 'RUNNABLE';
    const running = kernel === 'rcore' ? 'Running' : 'RUNNING';
    const done = kernel === 'rcore' ? 'Exited' : 'UNUSED';
    const absent = kernel === 'rcore' ? 'Exited' : 'UNUSED';
    const b = alone ? absent : ready;
    function step(title, explanation, aState, bState, execution, current, count, active, edge = '') {
      return {title, explanation, aState, bState, execution, current, count, active, edge};
    }
    const steps = [
      step('A 正在执行', 'A 已获得处理器，用户程序正在运行。', running, b, 'A：用户态', 'A', 0, 'a'),
      step(timer ? '时钟中断进入内核' : '系统调用进入内核', timer
        ? '异常入口保存用户状态。内核设置下一次定时器，再进入暂停接口。'
        : '异常入口保存用户状态，系统调用处理函数进入退出或让出接口。', running, b, 'A：内核态', 'A', 0, 'a'),
      step(exiting ? 'A 失去调度资格' : 'A 重新就绪', exiting
        ? '退出接口更新 A 的状态。本示例中 B 仍然就绪，内核继续调度 B。'
        : '暂停接口将 A 设为就绪，保留其上下文和后续运行资格。', exiting ? done : ready, b, 'A：内核态', 'A', 0, 'a')
    ];
    if (kernel === 'rcore') {
      const target = alone ? 'A' : 'B';
      steps.push(step('选择下一个任务', '从 A 后面的编号开始轮转扫描，最后检查 A 自身。更新目标状态和 current_task。',
        alone ? running : (exiting ? done : ready), alone ? absent : running, 'A：准备切换', target, 0, 'scheduler', 'first'));
      if (alone) {
        steps.push(step('选中 A，直接返回', 'next == current，run_next_task 直接返回，没有调用 __switch。', running, absent, 'A：内核态', 'A', 0, 'a'));
      } else {
        steps.push(step('保存 A，恢复 B', '释放任务管理器借用后调用 __switch。恢复 B 的 ra、sp 和 s0—s11，继续 B 的内核执行。', exiting ? done : ready, running, 'B：内核态', 'B', 1, 'b', 'second'));
      }
      steps.push(step(`${target} 返回用户态`, '完成内核处理后恢复用户寄存器，执行 sret。', alone ? running : (exiting ? done : ready), alone ? absent : running, `${target}：用户态`, target, alone ? 0 : 1, alone ? 'a' : 'b'));
    } else {
      steps.push(step('返回调度器', 'sched 调用 swtch，保存 A 的上下文并恢复 idle.context。current_proc 仍指向 A。', exiting ? done : ready, b, 'scheduler：内核态', 'A（上一进程）', 1, 'scheduler', 'first'));
      const target = alone ? 'A' : 'B';
      steps.push(step(`调度器选择 ${target}`, '继续扫描进程表，将目标设为 RUNNING，并更新 current_proc。', alone ? running : (exiting ? done : ready), alone ? absent : running, 'scheduler：准备切换', target, 1, 'scheduler'));
      steps.push(step(`恢复 ${target}`, 'swtch 保存调度器上下文，恢复目标进程的上下文。本例至此调用了两次切换汇编。', alone ? running : (exiting ? done : ready), alone ? absent : running, `${target}：内核态`, target, 2, alone ? 'a' : 'b', 'second'));
      steps.push(step(`${target} 返回用户态`, '恢复原有内核调用后完成处理，通过 usertrapret 与 userret 返回用户程序。', alone ? running : (exiting ? done : ready), alone ? absent : running, `${target}：用户态`, target, 2, alone ? 'a' : 'b'));
    }
    return steps;
  }

  if (typeof module !== 'undefined' && module.exports) module.exports = {stepsFor};
  if (!root.document) return;
  const doc = root.document;
  const get = id => doc.getElementById(id);
  const params = new URLSearchParams(root.location.search);
  if (['rcore', 'ucore'].includes(params.get('kernel'))) get('kernel').value = params.get('kernel');
  if (['yield', 'timer', 'exit', 'alone'].includes(params.get('scenario'))) get('scenario').value = params.get('scenario');
  const initialStep = Number(params.get('step'));
  const returnPath = params.get('return');
  if (returnPath && /^(index|rcore|ucore)\.html(?:#[^\s]*)?$/.test(returnPath)) {
    get('return-to-lesson').href = '../ch3/' + returnPath;
    get('return-to-lesson').textContent = '返回阅读位置';
  }
  let index = 0;
  let steps;
  function draw() {
    const s = steps[index];
    const alone = get('scenario').value === 'alone';
    get('step-title').textContent = s.title;
    get('explanation').textContent = s.explanation;
    for (const [id, field] of [['execution', 'execution'], ['current', 'current'], ['switch-count', 'count'], ['svg-a', 'aState'], ['svg-b', 'bState']]) {
      get(id).textContent = String(s[field]);
    }
    for (const node of ['a', 'scheduler', 'b']) get(`node-${node}`).classList.toggle('active', s.active === node);
    if (alone && get('kernel').value === 'ucore') {
      get('svg-b').textContent = s.aState;
      if (index >= steps.length - 2) {
        get('node-a').classList.remove('active');
        get('node-b').classList.add('active');
      }
    }
    for (const edge of ['first', 'second']) get(`edge-${edge}`).classList.toggle('active', s.edge === edge);
    get('progress').textContent = `${index + 1} / ${steps.length}`;
    get('step').value = String(index);
    get('previous').disabled = index === 0;
    get('next').disabled = index === steps.length - 1;
    const url = new URL(root.location.href);
    url.searchParams.set('kernel', get('kernel').value);
    url.searchParams.set('scenario', get('scenario').value);
    url.searchParams.set('step', String(index + 1));
    root.history.replaceState(null, '', url);
  }
  function reset() {
    index = 0;
    steps = stepsFor(get('kernel').value, get('scenario').value);
    const rcore = get('kernel').value === 'rcore';
    get('middle-label').textContent = rcore ? '选择任务' : '调度器';
    get('svg-middle').textContent = rcore ? 'A 的内核态' : 'idle.context';
    const alone = get('scenario').value === 'alone';
    get('target-label').textContent = alone ? (rcore ? '其他任务' : 'A（恢复）') : 'B';
    get('edge-second').hidden = alone && rcore;
    get('step').replaceChildren(...steps.map((s, i) => {
      const option = doc.createElement('option');
      option.value = String(i);
      option.textContent = `${i + 1}. ${s.title}`;
      return option;
    }));
    draw();
  }
  get('kernel').addEventListener('change', reset);
  get('scenario').addEventListener('change', reset);
  get('step').addEventListener('change', () => { index = Number(get('step').value); draw(); });
  get('reset').addEventListener('click', reset);
  get('previous').addEventListener('click', () => { if (index > 0) { index--; draw(); } });
  get('next').addEventListener('click', () => { if (index < steps.length - 1) { index++; draw(); } });
  reset();
  if (Number.isInteger(initialStep) && initialStep >= 1 && initialStep <= steps.length) {
    index = initialStep - 1;
    draw();
  }
  get('controls').hidden = false;
  doc.querySelector('details').open = false;
})(typeof globalThis !== 'undefined' ? globalThis : this);
