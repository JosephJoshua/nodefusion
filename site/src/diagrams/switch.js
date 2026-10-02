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
  function executionLane(s) {
    if (s.execution.startsWith('scheduler')) return 2;
    if (s.execution.startsWith('B')) return s.execution.includes('用户态') ? 4 : 3;
    return s.execution.includes('用户态') ? 0 : 1;
  }
  function drawExecution() {
    const svg = get('execution-path'), el = root.DiagramExplorer.svg;
    const focused = [...svg.querySelectorAll('[role=button]')].indexOf(doc.activeElement);
    const width = Math.max(320, Math.min(680, svg.parentElement.clientWidth));
    svg.setAttribute('viewBox', `0 0 ${width} 300`);
    svg.replaceChildren();
    const lanes = ['A 用户态', 'A 内核态', '调度器', 'B 内核态', 'B 用户态'];
    const x = i => 100 + i * (width - 120) / (steps.length - 1), y = s => 42 + executionLane(s) * 48;
    lanes.forEach((name, i) => {
      svg.append(el('line', {x1: 100, x2: width - 20, y1: 42 + i * 48, y2: 42 + i * 48, class: 'plot-grid'}));
      svg.append(el('text', {x: 88, y: 47 + i * 48, 'text-anchor': 'end', class: 'lane-label'}, name));
    });
    svg.append(el('text', {x: width - 20, y: 290, 'text-anchor': 'end', class: 'axis-label'}, '执行顺序 →'));
    for (let i = 1; i < steps.length; i++) {
      const before = steps[i - 1], after = steps[i];
      const d = `M${x(i - 1)} ${y(before)} H${x(i)} V${y(after)}`;
      const switching = after.count > before.count;
      svg.append(el('path', {d, class: `execution-segment ${i <= index ? 'visited' : ''} ${switching ? 'context-switch' : ''}`}));
    }
    steps.forEach((s, i) => {
      const group = el('g', {role: 'button', tabindex: 0, 'aria-label': `${i + 1}：${s.title}`, 'aria-pressed': i === index, class: `execution-stop ${i === index ? 'selected' : ''}`});
      group.append(el('circle', {cx: x(i), cy: y(s), r: 17, class: 'stop-hit'}), el('circle', {cx: x(i), cy: y(s), r: i === index ? 7 : 4, class: 'stop-dot'}));
      svg.append(el('text', {x: x(i), y: 270, 'text-anchor': 'middle', class: 'axis-label'}, i + 1));
      const choose = () => { index = i; draw(); get('execution-path').querySelectorAll('[role=button]')[i].focus({preventScroll: true}); };
      group.addEventListener('click', choose);
      group.addEventListener('keydown', event => {
        if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); choose(); }
        if (['ArrowLeft', 'ArrowRight'].includes(event.key)) {
          event.preventDefault(); index = Math.max(0, Math.min(steps.length - 1, i + (event.key === 'ArrowRight' ? 1 : -1))); draw();
          get('execution-path').querySelectorAll('[role=button]')[index].focus({preventScroll: true});
        }
      });
      svg.append(group);
    });
    if (focused >= 0) svg.querySelectorAll('[role=button]')[focused]?.focus({preventScroll: true});
    const s = steps[index], previous = steps[Math.max(0, index - 1)];
    const trap = index === 1, restore = index === steps.length - 1, switching = s.count > previous.count;
    const transfer = get('context-transfer'); transfer.replaceChildren();
    for (const [title, registers, active, direction] of [
      ['用户寄存器', get('kernel').value === 'rcore' ? '通用寄存器 · sepc · sstatus' : '通用寄存器 · epc', trap || restore, trap ? '保存到用户上下文' : '从用户上下文恢复'],
      ['内核上下文', 'ra · sp · s0–s11', switching, '保存当前上下文，恢复目标上下文']
    ]) {
      const row = doc.createElement('div'); row.className = active ? 'context-row active' : 'context-row';
      const heading = doc.createElement('strong'); heading.textContent = title;
      const values = doc.createElement('code'); values.textContent = registers;
      const action = doc.createElement('span'); action.textContent = active ? direction : '本步无保存或恢复';
      row.append(heading, values, action); transfer.append(row);
    }
    const compare = get('switch-comparison'); compare.replaceChildren();
    const target = get('scenario').value === 'alone' ? 'A' : 'B';
    for (const [name, row, points, label] of [['rCore', 42, [90, 330], target === 'A' ? '直接返回' : '__switch'], ['uCore', 112, [90, 210, 330], 'swtch']]) {
      compare.append(el('text', {x: 4, y: row + 5, class: 'lane-label'}, name));
      for (let i = 1; i < points.length; i++) {
        compare.append(el('path', {d: `M${points[i - 1] + 15} ${row} H${points[i] - 19} m-5 -4 l5 4 -5 4`, class: target === 'A' && name === 'rCore' ? 'comparison-skip' : 'comparison-edge'}));
        compare.append(el('text', {x: (points[i - 1] + points[i]) / 2, y: row - 18, 'text-anchor': 'middle', class: 'axis-label'}, label));
      }
      points.forEach((x, i) => {
        compare.append(el('circle', {cx: x, cy: row, r: 14, class: 'stop-dot'}));
        compare.append(el('text', {x, y: row + 5, 'text-anchor': 'middle', class: 'lane-label'}, i === 0 ? 'A' : i === points.length - 1 ? target : 'S'));
        if (i > 0 && i < points.length - 1) compare.append(el('text', {x, y: row + 31, 'text-anchor': 'middle', class: 'axis-label'}, '调度器'));
      });
    }
  }
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
    get('previous').disabled = index === 0;
    get('next').disabled = index === steps.length - 1;
    drawExecution();
    root.DiagramExplorer.timeline(get('step-timeline'), steps, index, next => { index = next; draw(); });
    const previous = steps[Math.max(0, index - 1)];
    root.DiagramExplorer.changes(get('state-changes'), ['aState', 'bState', 'current', 'count']
      .filter(field => previous[field] !== s[field])
      .map(field => [{aState: 'A 状态', bState: 'B 状态', current: '当前任务', count: '切换次数'}[field], previous[field], s[field]]));
    const scenario = get('scenario').value;
    get('rcore-count').textContent = String(stepsFor('rcore', scenario).at(-1).count);
    get('ucore-count').textContent = String(stepsFor('ucore', scenario).at(-1).count);
    get('switch-insight').textContent = alone
      ? '只剩 A 可运行时，rCore 选中自身并跳过 __switch；uCore 仍先回到调度器，再恢复 A。'
      : '异常入口保存用户寄存器；__switch 和 swtch 保存、恢复内核上下文。';
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
    draw();
  }
  get('kernel').addEventListener('change', reset);
  get('scenario').addEventListener('change', reset);
  get('reset').addEventListener('click', reset);
  get('previous').addEventListener('click', () => { if (index > 0) { index--; draw(); } });
  get('next').addEventListener('click', () => { if (index < steps.length - 1) { index++; draw(); } });
  new ResizeObserver(() => {
    const width = Math.max(320, Math.min(680, get('execution-path').parentElement.clientWidth));
    if (get('execution-path').getAttribute('viewBox') !== `0 0 ${width} 300`) drawExecution();
  }).observe(get('execution-path'));
  reset();
  if (Number.isInteger(initialStep) && initialStep >= 1 && initialStep <= steps.length) {
    index = initialStep - 1;
    draw();
  }
  get('controls').hidden = false;
  doc.querySelector('details').open = false;
})(typeof globalThis !== 'undefined' ? globalThis : this);
