(function () {
  'use strict';
  const scenarios = {
    mutex: [
      {title: 'A 持有锁', description: 'B、C 即将依次申请同一个阻塞互斥锁。', threads: ['运行 · 持锁', '就绪', '就绪'], states: ['running', 'ready', 'ready'], resource: 'A 持有 · locked = 1', queue: '空', ready: 'B、C'},
      {title: 'B、C 排队', description: 'B 和 C 申请已占用的锁，按顺序进入等待队列并停止运行。', threads: ['运行 · 持锁', '阻塞 · 等锁', '阻塞 · 等锁'], states: ['running', 'blocked', 'blocked'], resource: 'A 持有 · locked = 1', queue: 'B → C', ready: 'A'},
      {title: 'A 把锁交给 B', description: 'A 解锁时把锁交给队首 B。B 变为就绪；locked 仍为 1。', threads: ['就绪', '就绪 · 已获锁', '阻塞 · 等锁'], states: ['ready', 'ready', 'blocked'], resource: 'B 持有 · locked = 1', queue: 'C', ready: 'A、B'},
      {title: 'B 继续运行', description: 'B 从原来的 lock 调用返回，进入临界区，不再次申请锁。', threads: ['就绪', '运行 · 持锁', '阻塞 · 等锁'], states: ['ready', 'running', 'blocked'], resource: 'B 持有 · locked = 1', queue: 'C', ready: 'A'},
      {title: 'B 把锁交给 C', description: 'B 解锁时将同一把锁交给 C，等待队列变为空。', threads: ['就绪', '就绪', '就绪 · 已获锁'], states: ['ready', 'ready', 'ready'], resource: 'C 持有 · locked = 1', queue: '空', ready: 'A、B、C'}
    ],
    condvar: [
      {title: 'A 检查条件', description: 'A 持锁，发现共享条件尚未成立，准备调用 cond_wait。', threads: ['运行 · 持锁', '就绪', '—'], states: ['running', 'ready', 'idle'], resource: 'A 持有 · locked = 1', queue: '空', ready: 'B'},
      {title: 'A 进入条件变量队列', description: 'cond_wait 先解锁，再将 A 排入条件变量队列并阻塞。', threads: ['阻塞 · 等通知', '就绪', '—'], states: ['blocked', 'ready', 'idle'], resource: '空闲 · locked = 0', queue: '条件变量：A', ready: 'B'},
      {title: 'B 修改条件并通知', description: 'B 持锁修改共享变量，然后 signal。A 离开条件变量队列并就绪；B 仍持锁。', threads: ['就绪 · 待重新加锁', '运行 · 持锁', '—'], states: ['ready', 'running', 'idle'], resource: 'B 持有 · locked = 1', queue: '空', ready: 'A'},
      {title: 'A 再次等待锁', description: 'A 恢复执行 cond_wait，调用 mutex_lock；因为 B 尚未解锁，A 转入锁的等待队列。', threads: ['阻塞 · 等锁', '运行 · 持锁', '—'], states: ['blocked', 'running', 'idle'], resource: 'B 持有 · locked = 1', queue: '互斥锁：A', ready: 'B'},
      {title: 'B 把锁交给 A', description: 'B 解锁，锁直接交给 A。A 就绪后从 cond_wait 返回，再检查共享条件。', threads: ['就绪 · 已获锁', '就绪', '—'], states: ['ready', 'ready', 'idle'], resource: 'A 持有 · locked = 1', queue: '空', ready: 'A、B'}
    ],
    semaphore: [
      {title: '初值为 0', description: 'A、B 准备依次调用 down；目前没有可用许可。', threads: ['就绪', '就绪', '就绪'], states: ['ready', 'ready', 'ready'], resource: 'count = 0', queue: '空', ready: 'A、B、C'},
      {title: 'A 调用 down', description: 'count 减为 −1，A 排队并阻塞。', threads: ['阻塞 · 等许可', '就绪', '就绪'], states: ['blocked', 'ready', 'ready'], resource: 'count = −1', queue: 'A', ready: 'B、C'},
      {title: 'B 调用 down', description: 'count 减为 −2，B 排在 A 后面。', threads: ['阻塞 · 等许可', '阻塞 · 等许可', '就绪'], states: ['blocked', 'blocked', 'ready'], resource: 'count = −2', queue: 'A → B', ready: 'C'},
      {title: 'C 第一次 up', description: 'count 增为 −1，队首 A 获得许可并就绪。', threads: ['就绪 · 已获许可', '阻塞 · 等许可', '运行'], states: ['ready', 'blocked', 'running'], resource: 'count = −1', queue: 'B', ready: 'A、C'},
      {title: 'C 第二次 up', description: 'count 增为 0，B 获得许可并就绪；两个 down 恢复后都不再减数。', threads: ['就绪 · 已获许可', '就绪 · 已获许可', '运行'], states: ['ready', 'ready', 'running'], resource: 'count = 0', queue: '空', ready: 'A、B、C'}
    ]
  };
  if (typeof module !== 'undefined') module.exports = {scenarios};
  if (typeof document === 'undefined') return;
  const $ = id => document.getElementById(id);
  let step = 0;
  const scenario = $('scenario');
  let free = false;
  let experiment = SyncModel.create(scenario.value);
  let history = [];
  let lastDiagram;
  function queueDiagram(state, owner, queues) {
    const svg = $('queue-diagram'), el = DiagramExplorer.svg;
    const focused = svg.contains(document.activeElement) ? document.activeElement.id : null;
    lastDiagram = {state, owner, queues};
    const width = Math.max(320, Math.min(640, svg.parentElement.clientWidth)), compact = width < 450;
    const rowHeight = compact ? 46 : 58, first = compact ? 120 : 160, spacing = compact ? 62 : 86;
    const rows = [{label: free ? '可运行' : '运行 / 就绪', names: ['A', 'B', 'C'].filter((_, i) => ['ready', 'running'].includes(state.states[i]) && owner !== 'ABC'[i])},
      {label: scenario.value === 'semaphore' ? '信号量计数' : '持锁', names: owner ? [owner] : []}, ...queues];
    svg.setAttribute('viewBox', `0 0 ${width} ${rows.length * rowHeight + 28}`);
    const signature = width + ':' + rows.map(row => row.label).join('|');
    if (svg.dataset.rows !== signature) {
      svg.dataset.rows = signature; svg.replaceChildren();
      rows.forEach((row, i) => {
        svg.append(el('text', {x: compact ? 88 : 90, y: 44 + i * rowHeight, 'text-anchor': 'end', class: 'lane-label'}, row.label));
        svg.append(el('line', {x1: compact ? 104 : 116, x2: width - 20, y1: 40 + i * rowHeight, y2: 40 + i * rowHeight, class: 'queue-line'}));
      });
      for (const name of ['A', 'B', 'C']) {
        const token = el('g', {id: 'thread-' + name.toLowerCase(), class: 'moving-thread', 'data-actor': name, role: 'button', tabindex: 0});
        token.style.transition = 'none';
        requestAnimationFrame(() => requestAnimationFrame(() => { token.style.transition = ''; }));
        token.append(el('circle', {r: 23, class: 'thread-focus'}), el('circle', {r: 19, class: 'thread-body'}), el('text', {y: 5, 'text-anchor': 'middle'}, name), el('title', {}, `线程 ${name}`));
        const choose = () => { $('lab-actor').value = name; render(); $('thread-' + name.toLowerCase())?.focus({preventScroll: true}); };
        token.addEventListener('pointerdown', event => { if (event.button === 0) event.preventDefault(); });
        token.addEventListener('click', choose);
        token.addEventListener('keydown', event => {
          if (['Enter', ' '].includes(event.key)) { event.preventDefault(); event.stopPropagation(); choose(); }
          if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) {
            event.preventDefault(); event.stopPropagation();
            const visible = [...svg.querySelectorAll('[role=button]')].filter(thread => thread.style.display !== 'none');
            const index = visible.indexOf(token);
            const next = event.key === 'Home' ? 0 : event.key === 'End' ? visible.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + visible.length) % visible.length;
            visible[next].focus({preventScroll: true});
          }
        });
        svg.append(token);
      }
      const count = el('text', {x: first, y: 45 + rowHeight, class: 'permit-count', id: 'diagram-permits'}); svg.append(count);
      svg.append(el('text', {x: width - 20, y: rows.length * rowHeight + 14, 'text-anchor': 'end', class: 'axis-label'}, '等待队列：左侧为队首'));
    }
    for (const name of ['A', 'B', 'C']) {
      const token = svg.querySelector(`[data-actor=${name}]`);
      const row = rows.findIndex(row => row.names.includes(name));
      token.style.display = row < 0 ? 'none' : '';
      token.setAttribute('aria-pressed', String($('lab-actor').value === name));
      token.setAttribute('aria-label', `线程 ${name}：${state.threads['ABC'.indexOf(name)]}`);
      if (row >= 0) {
        token.style.transform = `translate(${first + rows[row].names.indexOf(name) * spacing}px, ${40 + row * rowHeight}px)`;
        token.dataset.state = row > 1 ? 'blocked' : row === 1 ? 'owner' : 'ready';
        token.querySelector('title').textContent = `线程 ${name}：${rows[row].label}`;
      }
    }
    $('diagram-permits').textContent = scenario.value === 'semaphore' ? state.resource : '';
    svg.setAttribute('aria-label', rows.map(row => `${row.label}：${row.names.join('、') || (row.label === '信号量计数' ? state.resource : '空')}`).join('；'));
    if (focused) $(focused)?.focus({preventScroll: true});
  }
  function renderLab() {
    const actor = $('lab-actor').value, model = experiment;
    const allBlocked = SyncModel.actors.every(name => model.threads[name].blocked);
    $('lab-message').textContent = allBlocked ? '三个线程均已阻塞，没有线程继续执行。可撤销上一步或重置。' :
      model.threads[actor].blocked ? `${actor} 正在${ {lock: '等待锁', condition: '等待条件变量通知', permit: '等待许可'}[model.threads[actor].blocked] }。选择其他可运行线程继续操作。` : model.message;
    $('permit-setting').hidden = scenario.value !== 'semaphore';
    $('permit-setting').parentElement.hidden = scenario.value !== 'semaphore';
    $('lab-undo').disabled = !history.length;
    const operations = scenario.value === 'semaphore' ? [['down', 'down：获取许可'], ['up', 'up：增加许可']] :
      [['lock', model.threads[actor].reacquire ? '继续 wait：重新加锁' : 'lock：申请锁'], ['unlock', 'unlock：释放锁'],
        ...(scenario.value === 'condvar' ? [['wait', 'wait：等待条件'], ['signal', 'signal：通知']] : [])];
    $('lab-actions').replaceChildren(...operations.map(([operation, label]) => {
      const button = document.createElement('button'); button.type = 'button'; button.textContent = label; button.dataset.operation = operation;
      button.disabled = !SyncModel.allowed(model, actor, operation);
      button.onclick = () => {
        history.push(structuredClone(experiment)); if (history.length > 64) history.shift();
        experiment = SyncModel.apply(experiment, actor, operation); render();
        const same = $('lab-actions').querySelector(`[data-operation=${operation}]`);
        const next = same && !same.disabled ? same : $('lab-actions').querySelector('button:not(:disabled)') || $('lab-actor');
        next.focus({preventScroll: true});
      };
      return button;
    }));
    const states = SyncModel.actors.map(name => model.threads[name].blocked ? 'blocked' : 'ready');
    const threads = SyncModel.actors.map(name => model.threads[name].blocked ?
      `阻塞 · ${ {lock: '等锁', condition: '等通知', permit: '等许可'}[model.threads[name].blocked] }` :
      model.owner === name ? '可运行 · 已获锁' : model.threads[name].reacquire ? '可运行 · 待重新加锁' : '可运行');
    const queue = scenario.value === 'semaphore' ? model.permitQueue : model.lockQueue;
    const resource = scenario.value === 'semaphore' ? `count = ${model.count}` : `${model.owner ? `${model.owner} 持有` : '空闲'} · locked = ${model.owner ? 1 : 0}`;
    return {states, threads, resource, queue: scenario.value === 'condvar' ? `锁：${queue.join(' → ') || '空'}；条件变量：${model.conditionQueue.join(' → ') || '空'}` : queue.join(' → ') || '空', owner: model.owner,
      queues: [{label: scenario.value === 'semaphore' ? '等待许可' : '等待锁', names: queue}, ...(scenario.value === 'condvar' ? [{label: '等待通知', names: model.conditionQueue}] : [])]};
  }
  function render() {
    const list = scenarios[scenario.value];
    const state = free ? renderLab() : list[step];
    if (state.states['ABC'.indexOf($('lab-actor').value)] === 'idle') $('lab-actor').value = 'A';
    $('sync-lab').hidden = !free;
    $('lab-history').hidden = !free;
    $('controls').dataset.mode = free ? 'free' : 'guided';
    document.querySelector('.step-panel').hidden = free;
    $('guided-transport').hidden = free;
    $('guided-mode').setAttribute('aria-pressed', String(!free)); $('free-mode').setAttribute('aria-pressed', String(free));
    $('actor-status').textContent = state.threads['ABC'.indexOf($('lab-actor').value)];
    [...$('lab-actor').options].forEach((option, index) => { option.disabled = state.states[index] === 'idle'; });
    $('resource-name').textContent = scenario.value === 'semaphore' ? '信号量' : '互斥锁';
    $('resource-value').textContent = state.resource;
    $('queue-value').textContent = state.queue;
    $('step-title').textContent = state.title || '';
    $('step-description').textContent = state.description || '';
    $('previous').disabled = step === 0;
    $('next').disabled = step === list.length - 1;
    DiagramExplorer.timeline($('step-timeline'), list, step, index => { step = index; render(); });
    const owner = free ? state.owner : state.resource.match(/^([ABC]) 持有/)?.[1];
    const waiting = state.queue.match(/[ABC]/g) || [];
    queueDiagram(state, owner, free ? state.queues : [{label: scenario.value === 'semaphore' ? '等待许可' : '等待锁', names: state.queue.includes('条件变量') ? [] : waiting},
      ...(scenario.value === 'condvar' ? [{label: '等待通知', names: state.queue.includes('条件变量') ? waiting : []}] : [])]);
    const previous = list[Math.max(0, step - 1)];
    DiagramExplorer.changes($('state-changes'), ['resource', 'queue'].filter(field => previous[field] !== state[field])
      .map(field => [field === 'resource' ? '同步对象' : '等待队列', previous[field], state[field]]));
    $('sync-insight').textContent = {
      mutex: '解锁时有等待线程，锁直接交给队首。线程变为就绪后仍需被调度，才能继续执行临界区。',
      condvar: 'signal 使等待线程就绪。cond_wait 返回前还会重新加锁；发出通知的线程仍持锁时，被唤醒的线程可能再次阻塞。',
      semaphore: 'count < 0 时，其绝对值对应等待线程数。up 将许可交给队首，被唤醒的 down 从原调用处继续。'
    }[scenario.value];
    $('controls').hidden = false;
    $('static-diagram').open = false;
  }
  function resetLab() { experiment = SyncModel.create(scenario.value, Number($('lab-permits').value)); history = []; }
  scenario.addEventListener('change', () => { step = 0; resetLab(); render(); });
  $('free-mode').addEventListener('click', () => { free = true; render(); });
  $('guided-mode').addEventListener('click', () => { free = false; render(); });
  $('lab-actor').addEventListener('change', render);
  $('lab-permits').addEventListener('change', () => { resetLab(); render(); });
  $('lab-reset').addEventListener('click', () => { resetLab(); render(); });
  $('lab-undo').addEventListener('click', () => { if (history.length) { experiment = history.pop(); render(); } });
  new ResizeObserver(() => { if (lastDiagram) queueDiagram(lastDiagram.state, lastDiagram.owner, lastDiagram.queues); }).observe($('queue-diagram'));
  $('previous').addEventListener('click', () => { if (step > 0) { step--; render(); } });
  $('next').addEventListener('click', () => { if (step < scenarios[scenario.value].length - 1) { step++; render(); } });
  $('reset').addEventListener('click', () => { step = 0; render(); });
  document.addEventListener('keydown', event => {
    if (free) return;
    if (event.target instanceof HTMLElement && ['SELECT', 'BUTTON', 'INPUT'].includes(event.target.tagName)) return;
    if (event.key === 'ArrowRight' && step < scenarios[scenario.value].length - 1) { step++; render(); event.stopPropagation(); event.preventDefault(); }
    if (event.key === 'ArrowLeft' && step > 0) { step--; render(); event.stopPropagation(); event.preventDefault(); }
  });
  const requested = new URLSearchParams(location.search).get('scenario');
  if (requested in scenarios) scenario.value = requested;
  resetLab();
  render();
})();
