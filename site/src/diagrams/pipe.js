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
  let operationStep = 0;
  let message = '运行写进程，观察缓冲区占用。';
  const names = {reader: '读进程', writer: '写进程'};
  function drawBuffer() {
    const count = unread(state), head = state.readCount % state.capacity, tail = state.writeCount % state.capacity;
    const point = (index, radius) => {
      const angle = index / state.capacity * Math.PI * 2 - Math.PI / 2;
      return [120 + radius * Math.cos(angle), 120 + radius * Math.sin(angle)];
    };
    const arc = doc.getElementById('unread-arc');
    if (!count) arc.setAttribute('d', '');
    else if (count === state.capacity) arc.setAttribute('d', 'M120 36 A84 84 0 1 1 120 204 A84 84 0 1 1 120 36');
    else {
      const start = point(head, 84), end = point(head + count, 84);
      arc.setAttribute('d', `M${start.join(' ')} A84 84 0 ${count > state.capacity / 2 ? 1 : 0} 1 ${end.join(' ')}`);
    }
    for (const [id, index, near, far] of [['read-pointer', head, 64, 96], ['write-pointer', tail, 98, 110]]) {
      const a = point(index, near), b = point(index, far), node = doc.getElementById(id);
      for (const [key, value] of Object.entries({x1: a[0], y1: a[1], x2: b[0], y2: b[1]})) node.setAttribute(key, value);
    }
    doc.getElementById('ring-count').textContent = `${count} / ${state.capacity}`;
    doc.getElementById('ring-quarter').textContent = String(state.capacity / 4);
    doc.getElementById('ring-unit').textContent = `每格 ${state.capacity / 32} 字节`;
    doc.getElementById('read-index-label').textContent = `${state.kernel === 'rcore' ? 'head' : '读下标'} = ${head}`;
    doc.getElementById('write-index-label').textContent = `${state.kernel === 'rcore' ? 'tail' : '写下标'} = ${tail}`;
    doc.getElementById('buffer-circle').setAttribute('aria-label', `环形缓冲区：读下标 ${head}，写下标 ${tail}，未读 ${count} 字节。橙色为读指针，青色为写指针。`);
    const input = doc.getElementById('byte-index'); input.max = String(state.capacity - 1);
    if (input.valueAsNumber >= state.capacity) input.value = state.capacity - 1;
    const index = input.valueAsNumber;
    const selected = doc.getElementById('selected-byte');
    const selectedPoint = point((Number.isInteger(index) ? index : 0) + .5, 84);
    selected.setAttribute('cx', selectedPoint[0]); selected.setAttribute('cy', selectedPoint[1]);
    selected.style.display = input.validity.valid && input.value !== '' ? '' : 'none';
    const cells = doc.getElementById('ring-cells');
    if (cells.dataset.capacity !== String(state.capacity)) {
      cells.dataset.capacity = state.capacity; cells.replaceChildren();
      const divisions = 32;
      for (let i = 0; i < divisions; i++) {
        const a = point(i * state.capacity / divisions, 74), b = point(i * state.capacity / divisions, 94);
        cells.append(DiagramExplorer.svg('line', {x1: a[0], y1: a[1], x2: b[0], y2: b[1], class: 'ring-division'}));
      }
    }
    const active = Number.isInteger(index) && index >= 0 && index < state.capacity && (index - head + state.capacity) % state.capacity < count;
    doc.getElementById('byte-value').textContent = input.validity.valid && input.value !== ''
      ? `buffer[${index}]\n${active ? '未读：0x' + state.buffer[index].toString(16).padStart(2, '0') : '空闲'}` : `输入 0–${state.capacity - 1}`;
    const bytes = doc.getElementById('pipe-bytes'); bytes.replaceChildren();
    const start = Math.floor((Number.isInteger(index) && input.validity.valid ? index : 0) / 8) * 8;
    for (let slot = start; slot < Math.min(start + 8, state.capacity); slot++) {
      const isUnread = (slot - head + state.capacity) % state.capacity < count;
      const button = doc.createElement('button'); button.type = 'button'; button.dataset.unread = String(isUnread);
      button.setAttribute('aria-pressed', String(slot === index));
      button.setAttribute('aria-label', `buffer[${slot}]：${isUnread ? '未读 ' + state.buffer[slot].toString(16).padStart(2, '0') : '空闲'}`);
      const position = doc.createElement('span'); position.textContent = slot;
      const value = doc.createElement('code'); value.textContent = isUnread ? state.buffer[slot].toString(16).padStart(2, '0') : '·';
      button.append(position, value); button.onclick = () => { input.value = slot; drawBuffer(); bytes.querySelector(`[aria-pressed=true]`)?.focus({preventScroll: true}); }; bytes.append(button);
    }
    for (const [actor, id] of [['writer', 'write'], ['reader', 'read']]) {
      const operation = state[actor];
      const progress = doc.getElementById(id + '-progress');
      progress.max = operation?.length || 1; progress.value = operation?.done || 0;
      doc.getElementById(id + '-progress-label').textContent = `${operation?.done || 0}/${operation?.length || 0}`;
    }
    doc.getElementById('pipe-insight').textContent = state.released ? '两端已关闭，缓冲区不再可读写。'
      : !state.readerOpen && state.kernel === 'ucore' ? '读端已关闭，uCore 的写操作返回 −1。'
      : !state.readerOpen ? '读端已关闭，没有进程继续消费缓冲区。rCore 的写操作仍可填入剩余空间，写满后让出。' : count === state.capacity
      ? `缓冲区已满。读进程读出数据后，写进程才有空间继续。${state.kernel === 'rcore' ? 'head = tail，status = Full。' : 'nwrite − nread = 512。'}`
      : count === 0 ? `缓冲区为空。${state.writerOpen ? '写端仍打开，读进程需要等待后续写入。' : state.kernel === 'rcore' ? '写端已关闭，rCore 读操作返回已读字节数。' : '写端已关闭，uCore 读操作返回 −1。'}`
        : `可读 ${count} 字节，可写 ${state.capacity - count} 字节。${state.kernel === 'ucore' ? 'uCore 已读到部分数据后遇到空缓冲区，会返回短读。' : 'rCore 按请求长度继续读取，读空时让出并保留请求。'}`;
  }
  function formatOperation(operation) {
    if (!operation) return '尚未发起请求';
    if (operation.panic) return 'panic：请求长度为零';
    if (operation.result !== null) return `已传输 ${operation.done} / ${operation.length} 字节；返回 ${operation.result}`;
    return operation.yields ? `已传输 ${operation.done} / ${operation.length} 字节；已让出 ${operation.yields} 次` :
      `待执行 · ${operation.length} 字节`;
  }
  function render() {
    const count = state.released ? 0 : unread(state);
    doc.getElementById('occupancy').textContent = `${count} / ${state.capacity} 字节`;
    const positions = doc.getElementById('positions');
    positions.replaceChildren();
    const counters = state.kernel === 'rcore' ?
      [['status', count === 0 ? 'Empty' : count === state.capacity ? 'Full' : 'Normal']] :
      [['nread', state.readCount], ['nwrite', state.writeCount]];
    if (!state.released) for (const [name, value] of counters) {
      const field = doc.createElement('span'); field.textContent = `${name} = ${value}`; positions.append(field);
    }
    doc.getElementById('formula').textContent = state.kernel === 'rcore' ?
      'head 和 tail 相等时，用 status 区分空与满。' : '可读字节数 = nwrite − nread（无符号运算）；数组下标 = 计数 % 512。';
    doc.getElementById('resource').textContent = state.released ? '两端均已关闭，缓冲区已释放。' :
      `读端${state.readerOpen ? '打开' : '关闭'}；写端${state.writerOpen ? '打开' : '关闭'}。`;
    for (const actor of ['reader', 'writer']) {
      doc.getElementById(actor + '-status').textContent = formatOperation(state[actor]);
      doc.getElementById(actor + '-run').disabled = !state[actor + 'Open'] && !pending(state[actor]);
      doc.getElementById(actor + '-close').disabled = !state[actor + 'Open'] || pending(state[actor]);
      const length = doc.getElementById(actor + '-length');
      length.disabled = pending(state[actor]) || !state[actor + 'Open'];
      if (pending(state[actor])) length.value = state[actor].length;
    }
    doc.getElementById('undo').disabled = !history.length;
    doc.getElementById('result').textContent = message;
    doc.getElementById('received').textContent = state.reader?.values.length ?
      `本次读取的前 16 字节：${state.reader.values.slice(0, 16).map(n => n.toString(16).padStart(2, '0')).join(' ')}` : '写入数据按 00、01、…、ff 循环，用于检查 FIFO 顺序。';
    drawBuffer();
    drawOccupancy();
  }
  function drawOccupancy() {
    const svg = doc.getElementById('occupancy-chart'), el = DiagramExplorer.svg;
    const width = Math.max(320, Math.min(640, svg.parentElement.clientWidth));
    svg.setAttribute('viewBox', `0 0 ${width} 190`);
    svg.replaceChildren();
    const samples = [...history.map(saved => ({step: saved.step, value: unread(saved.state)})), {step: operationStep, value: unread(state)}];
    const values = samples.map(sample => sample.value);
    const x = i => 62 + i * (width - 90) / Math.max(1, values.length - 1), y = value => 150 - value / state.capacity * 120;
    for (const value of [0, state.capacity / 2, state.capacity]) {
      svg.append(el('line', {x1: 62, x2: width - 28, y1: y(value), y2: y(value), class: 'plot-grid'}));
      svg.append(el('text', {x: 50, y: y(value) + 4, 'text-anchor': 'end', class: 'axis-label'}, value));
    }
    svg.append(el('text', {x: 12, y: 14, class: 'axis-label'}, '字节'));
    svg.append(el('path', {d: values.map((value, i) => `${i ? 'L' : 'M'}${x(i)} ${y(value)}`).join(' '), class: 'occupancy-line'}));
    values.forEach((value, i) => {
      const circle = el('circle', {cx: x(i), cy: y(value), r: 4, class: i === values.length - 1 ? 'current-sample' : 'sample'});
      circle.append(el('title', {}, `第 ${samples[i].step} 步：${value} 字节`)); svg.append(circle);
      if (i === 0 || i === values.length - 1 || values.length <= 8) svg.append(el('text', {x: x(i), y: 175, 'text-anchor': 'middle', class: 'axis-label'}, samples[i].step));
    });
    svg.setAttribute('aria-label', `缓冲区占用，单位字节：${values.join(' → ')}。横轴为操作顺序。`);
  }
  function change(action) {
    const saved = {state: structuredClone(state), message, step: operationStep};
    action();
    operationStep++;
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
  function reset() { state = preset(kernel.value, example.value); history = []; operationStep = 0; message = '运行进程，观察缓冲区占用。'; render(); }
  const processTabs = [...doc.querySelectorAll('[role="tab"]')];
  function chooseProcess(actor) {
    doc.querySelector('.processes').dataset.actor = actor;
    for (const tab of processTabs) {
      const selected = tab.dataset.actor === actor;
      tab.setAttribute('aria-selected', String(selected));
      tab.tabIndex = selected ? 0 : -1;
      doc.getElementById(tab.dataset.actor + '-process').hidden = !selected;
    }
  }
  for (const tab of processTabs) {
    tab.addEventListener('click', () => chooseProcess(tab.dataset.actor));
    tab.addEventListener('keydown', event => {
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      const next = processTabs[event.key === 'Home' ? 0 : event.key === 'End' ? 1 : processTabs.indexOf(tab) === 0 ? 1 : 0];
      chooseProcess(next.dataset.actor);
      next.focus({preventScroll: true});
    });
  }
  kernel.addEventListener('change', reset);
  doc.getElementById('byte-index').addEventListener('input', drawBuffer);
  new ResizeObserver(drawOccupancy).observe(doc.getElementById('occupancy-chart'));
  doc.getElementById('buffer-circle').addEventListener('click', event => {
    const svg = event.currentTarget;
    const point = new DOMPoint(event.clientX, event.clientY).matrixTransform(svg.getScreenCTM().inverse());
    const angle = (Math.atan2(point.y - 120, point.x - 120) + Math.PI / 2 + Math.PI * 2) % (Math.PI * 2);
    doc.getElementById('byte-index').value = Math.floor(angle / (Math.PI * 2) * state.capacity); drawBuffer();
  });
  doc.getElementById('buffer-circle').addEventListener('keydown', event => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const input = doc.getElementById('byte-index');
    input.value = event.key === 'Home' ? 0 : event.key === 'End' ? state.capacity - 1 : ((input.valueAsNumber || 0) + (event.key === 'ArrowRight' ? 1 : -1) + state.capacity) % state.capacity;
    drawBuffer();
  });
  example.addEventListener('change', reset);
  doc.getElementById('reset').addEventListener('click', reset);
  doc.getElementById('undo').addEventListener('click', () => { const saved = history.pop(); if (saved) { state = saved.state; message = saved.message; operationStep = saved.step; render(); } });
  render();
  doc.getElementById('controls').hidden = false;
  doc.getElementById('static-diagram').open = false;
})(typeof window === 'undefined' ? globalThis : window);
