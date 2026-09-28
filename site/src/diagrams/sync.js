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
  function render() {
    const list = scenarios[scenario.value];
    const state = list[step];
    ['a', 'b', 'c'].forEach((name, index) => {
      const card = $('thread-' + name);
      card.dataset.state = state.states[index];
      card.querySelector('span').textContent = state.threads[index];
    });
    $('resource-name').textContent = scenario.value === 'semaphore' ? '信号量' : '互斥锁';
    $('resource-value').textContent = state.resource;
    $('queue-name').textContent = '等待队列';
    $('queue-value').textContent = state.queue;
    $('step-label').textContent = `步骤 ${step + 1} / ${list.length}`;
    $('step-title').textContent = state.title;
    $('step-description').textContent = state.description;
    $('lock-state').textContent = state.resource;
    $('wait-state').textContent = state.queue;
    $('ready-state').textContent = state.ready;
    $('position').textContent = `${step + 1} / ${list.length}`;
    $('previous').disabled = step === 0;
    $('next').disabled = step === list.length - 1;
    $('controls').hidden = false;
    $('static-diagram').open = false;
  }
  scenario.addEventListener('change', () => { step = 0; render(); });
  $('previous').addEventListener('click', () => { if (step > 0) { step--; render(); } });
  $('next').addEventListener('click', () => { if (step < scenarios[scenario.value].length - 1) { step++; render(); } });
  $('reset').addEventListener('click', () => { step = 0; render(); });
  document.addEventListener('keydown', event => {
    if (event.target instanceof HTMLElement && ['SELECT', 'BUTTON', 'INPUT'].includes(event.target.tagName)) return;
    if (event.key === 'ArrowRight' && step < scenarios[scenario.value].length - 1) { step++; render(); event.stopPropagation(); event.preventDefault(); }
    if (event.key === 'ArrowLeft' && step > 0) { step--; render(); event.stopPropagation(); event.preventDefault(); }
  });
  const requested = new URLSearchParams(location.search).get('scenario');
  if (requested in scenarios) scenario.value = requested;
  render();
})();
