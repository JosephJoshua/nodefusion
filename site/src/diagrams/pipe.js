(function (root) {
  'use strict';
  const capacities = {rcore: 32, ucore: 512};
  function create(kernel) {
    if (!capacities[kernel]) throw new RangeError('Unknown kernel');
    return {kernel, capacity: capacities[kernel], readCount: 0, writeCount: 0,
      buffer: Array(capacities[kernel]).fill(null), readerOpen: true, writerOpen: true,
      reader: null, writer: null, released: false};
  }
  const unread = state => state.released ? 0 : state.kernel === 'ucore' ? (state.writeCount - state.readCount) >>> 0 : state.writeCount - state.readCount;
  const advance = (state, field, count) => { state[field] = state.kernel === 'ucore' ? (state[field] + count) >>> 0 : state[field] + count; };
  const pending = operation => operation && operation.result === null && !operation.panic;
  function start(state, actor, length) {
    if (!['reader', 'writer'].includes(actor) || !Number.isSafeInteger(length) || length < 0 || length > 4096) throw new RangeError('Invalid request');
    if (!state[actor + 'Open'] || pending(state[actor])) throw new Error('Endpoint unavailable');
    state[actor] = {length, done: 0, values: [], result: null, panic: false, yields: 0};
  }
  function close(state, actor) {
    if (!['reader', 'writer'].includes(actor) || !state[actor + 'Open'] || pending(state[actor])) throw new Error('Endpoint unavailable');
    state[actor + 'Open'] = false;
    if (!state.readerOpen && !state.writerOpen) {
      state.released = true;
      state.buffer.fill(null);
    }
  }
  function run(state, actor) {
    if (!['reader', 'writer'].includes(actor) || !pending(state[actor])) throw new Error('No pending request');
    const operation = state[actor];
    const chunks = [];
    const finish = result => { operation.result = result; return {kind: 'return', actor, result, chunks}; };
    const yieldNow = () => { operation.yields++; return {kind: 'yield', actor, chunks}; };
    if (operation.length === 0) {
      if (state.kernel === 'rcore') return finish(0);
      operation.panic = true;
      return {kind: 'panic', actor, chunks};
    }
    // Run one process until its function returns or explicitly yields.
    while (operation.done < operation.length) {
      if (actor === 'writer' && state.kernel === 'ucore' && !state.readerOpen) return finish(-1);
      const available = actor === 'reader' ? unread(state) : state.capacity - unread(state);
      if (!available) {
        if (actor === 'reader') {
          if (state.kernel === 'ucore' && operation.done) return finish(operation.done);
          if (!state.writerOpen) return finish(state.kernel === 'ucore' ? -1 : operation.done);
        }
        return yieldNow();
      }
      const field = actor === 'reader' ? 'readCount' : 'writeCount';
      const index = state[field] % state.capacity;
      const count = Math.min(operation.length - operation.done, available,
        state.kernel === 'ucore' ? state.capacity - index : Infinity);
      chunks.push({index, count});
      for (let i = 0; i < count; i++) {
        const position = (index + i) % state.capacity;
        if (actor === 'writer') state.buffer[position] = (operation.done + i) % 256;
        else operation.values.push(state.buffer[position]);
      }
      advance(state, field, count);
      operation.done += count;
    }
    return finish(operation.done);
  }
  function preset(kernel, name) {
    const state = create(kernel);
    if (name === 'short') { start(state, 'writer', 5); run(state, 'writer'); start(state, 'reader', 12); }
    else if (name === 'transfer') { start(state, 'writer', state.capacity + 8); start(state, 'reader', state.capacity + 8); }
    else if (name === 'wrap') {
      start(state, 'writer', state.capacity - 4); run(state, 'writer');
      start(state, 'reader', state.capacity - 8); run(state, 'reader');
      start(state, 'writer', 12);
    } else if (name === 'closed') { close(state, 'reader'); start(state, 'writer', state.capacity + 8); }
    else if (name !== 'empty') throw new RangeError('Unknown example');
    return state;
  }
  if (typeof module !== 'undefined' && module.exports) module.exports = {create, unread, pending, start, close, run, preset};
  if (!root.document) return;
  const doc = root.document;
  const kernel = doc.getElementById('kernel');
  const example = doc.getElementById('example');
  const params = new URLSearchParams(location.search);
  if (capacities[params.get('kernel')]) kernel.value = params.get('kernel');
  const returnTo = params.get('return');
  if (returnTo && /^(index|rcore|ucore)\.html(?:#.*)?$/.test(returnTo)) doc.getElementById('return-to-lesson').href = '../ch7/' + returnTo;
  let state = preset(kernel.value, example.value);
  let history = [];
  let message = '运行写进程，观察缓冲区占用。';
  const names = {reader: '读进程', writer: '写进程'};
  function formatOperation(operation) {
    if (!operation) return '尚未发起请求';
    if (operation.panic) return 'panic：请求长度为零';
    if (operation.result !== null) return `已传输 ${operation.done} / ${operation.length} 字节；返回 ${operation.result}`;
    return operation.yields ? `已传输 ${operation.done} / ${operation.length} 字节；已让出 ${operation.yields} 次` :
      `待执行 · ${operation.length} 字节`;
  }
  function render() {
    const count = state.released ? 0 : unread(state);
    const head = state.readCount % state.capacity;
    const tail = state.writeCount % state.capacity;
    doc.getElementById('occupancy').textContent = `${count} / ${state.capacity} 字节`;
    doc.getElementById('used').style.width = `${count / state.capacity * 100}%`;
    doc.getElementById('positions').textContent = state.released ? '' : state.kernel === 'rcore' ?
      `head = ${head}，tail = ${tail}，status = ${count === 0 ? 'Empty' : count === state.capacity ? 'Full' : 'Normal'}` :
      `nread = ${state.readCount}，nwrite = ${state.writeCount}；数组下标 ${head} / ${tail}`;
    doc.getElementById('formula').textContent = state.kernel === 'rcore' ?
      'head 和 tail 相等时，用 status 区分空与满。' : '可读字节数 = nwrite − nread；数组下标 = 计数 % 512。';
    doc.getElementById('resource').textContent = state.released ? '两端均已关闭，缓冲区已释放。' :
      `读端${state.readerOpen ? '打开' : '关闭'}；写端${state.writerOpen ? '打开' : '关闭'}。`;
    const ranges = [];
    for (let position = 0; position < state.capacity;) {
      const active = count > 0 && (position - head + state.capacity) % state.capacity < count;
      let end = position + 1;
      while (end < state.capacity && (count > 0 && (end - head + state.capacity) % state.capacity < count) === active) end++;
      const cell = doc.createElement('span');
      cell.className = active ? 'range occupied' : 'range';
      cell.style.flexGrow = String(end - position);
      cell.textContent = end - position === 1 ? String(position) : `${position}–${end - 1}`;
      cell.title = `${active ? '未读' : '空闲'}：${position} 到 ${end - 1}`;
      ranges.push(cell);
      position = end;
    }
    doc.getElementById('ring').replaceChildren(...ranges);
    for (const actor of ['reader', 'writer']) {
      doc.getElementById(actor + '-status').textContent = formatOperation(state[actor]);
      doc.getElementById(actor + '-run').disabled = !state[actor + 'Open'] && !pending(state[actor]);
      doc.getElementById(actor + '-close').disabled = !state[actor + 'Open'] || pending(state[actor]);
      doc.getElementById(actor + '-length').closest('label').hidden = pending(state[actor]) || !state[actor + 'Open'];
    }
    doc.getElementById('undo').disabled = !history.length;
    doc.getElementById('result').textContent = message;
    doc.getElementById('received').textContent = state.reader?.values.length ?
      `本次读取的前 16 字节：${state.reader.values.slice(0, 16).map(n => n.toString(16).padStart(2, '0')).join(' ')}` : '写入数据按 00、01、…、ff 循环，用于检查 FIFO 顺序。';
  }
  function change(action) {
    const saved = {state: structuredClone(state), message};
    action();
    history.push(saved);
    if (history.length > 24) history.shift();
    render();
  }
  for (const actor of ['reader', 'writer']) {
    const input = doc.getElementById(actor + '-length');
    doc.getElementById(actor + '-run').addEventListener('click', () => {
      if (!pending(state[actor]) && !input.reportValidity()) return;
      change(() => {
        if (!pending(state[actor])) start(state, actor, input.valueAsNumber);
        const event = run(state, actor);
        const count = event.chunks.reduce((sum, chunk) => sum + chunk.count, 0);
        const copying = count ? (state.kernel === 'rcore' ? `连续 ${count} 次 ${actor === 'reader' ? 'read_byte' : 'write_byte'}` :
          event.chunks.map(chunk => `${actor === 'reader' ? 'copyout' : 'copyin'}(${chunk.count})，下标 ${chunk.index}`).join('；')) + '。' : '';
        message = `${names[actor]}：${copying}${event.kind === 'yield' ? '缓冲区' + (actor === 'reader' ? '为空' : '已满') + '，主动让出处理器；请求仍未返回。' : `返回 ${event.result}。`}`;
      });
    });
    doc.getElementById(actor + '-close').addEventListener('click', () => change(() => {
      close(state, actor); message = `${names[actor]}关闭其端点。`;
    }));
  }
  function reset() { state = preset(kernel.value, example.value); history = []; message = '运行进程，观察缓冲区占用。'; render(); }
  const processTabs = [...doc.querySelectorAll('[role="tab"]')];
  function chooseProcess(actor) {
    doc.querySelector('.processes').dataset.actor = actor;
    for (const tab of processTabs) {
      const selected = tab.dataset.actor === actor;
      tab.setAttribute('aria-selected', String(selected));
      tab.tabIndex = selected ? 0 : -1;
    }
  }
  for (const tab of processTabs) {
    tab.addEventListener('click', () => chooseProcess(tab.dataset.actor));
    tab.addEventListener('keydown', event => {
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      const next = processTabs[event.key === 'Home' ? 0 : event.key === 'End' ? 1 : processTabs.indexOf(tab) === 0 ? 1 : 0];
      chooseProcess(next.dataset.actor);
      next.focus();
    });
  }
  kernel.addEventListener('change', reset);
  example.addEventListener('change', reset);
  doc.getElementById('reset').addEventListener('click', reset);
  doc.getElementById('undo').addEventListener('click', () => { const saved = history.pop(); if (saved) { state = saved.state; message = saved.message; render(); } });
  render();
  doc.getElementById('controls').hidden = false;
  doc.getElementById('static-diagram').open = false;
})(typeof window === 'undefined' ? globalThis : window);
