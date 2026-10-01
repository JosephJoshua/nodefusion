'use strict';

const NF = {
  runs: [],
  cur: 0,
  playing: false,
  speed: 260,
  loop: false,
  detailOpen: true,
  tab: 'overview',
  selEvent: null,
  selPage: null,
  selPid: null,
  filters: { text: '', kind: '', res: '', pid: '', cpu: '', group: '', from: '', to: '' },
  functionFilters: {text: '', cpu: '', limit: '80', grouping: null},
  functionFocusIndex: null,
  sourceSelection: {event: null, frame: 0, inline: 0},
  advancedFiltersOpen: false,
};


const $ = (s, r) => (r || document).querySelector(s);
const el = (tag, cls, txt) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (txt !== undefined) e.textContent = txt;
  return e;
};
const shortText = (value, limit = 160) => {
  const text = String(value || '').replace(/\s+/g, ' ').trim();
  return text.length > limit ? `${text.slice(0, limit - 1)}…` : text;
};
/* The bundle encodes integers beyond JS precision as hexadecimal strings. */
const EXACT_MAX = Number.MAX_SAFE_INTEGER;   // 2^53 - 1
const isHexStr = (n) => typeof n === 'string' && n.startsWith('0x');

const hex = (n) => {
  if (n === null || n === undefined) return '—';
  if (isHexStr(n)) return n;
  return '0x' + Number(n).toString(16);
};

const num = (n) => {
  if (n === null || n === undefined) return '—';
  if (isHexStr(n)) return n;
  const v = Number(n);
  if (!Number.isFinite(v)) return '—';
  if (Math.abs(v) > EXACT_MAX) return '0x' + v.toString(16);
  return v.toLocaleString('en-US');
};

const plain = (n) => ((n === null || n === undefined) ? '—' : String(n));

function fmtInsn(n) {
  if (n === null || n === undefined) return '—';
  return num(n);
}

async function inflateB64(b64) {
  const bin = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
  if (typeof DecompressionStream === 'undefined') {
    throw new Error('这个浏览器不支持 DecompressionStream，请用较新的 Chrome / Edge / Firefox 打开');
  }
  const stream = new Blob([bin]).stream().pipeThrough(new DecompressionStream('deflate'));
  const buf = await new Response(stream).arrayBuffer();
  return JSON.parse(new TextDecoder().decode(buf));
}


function stateIndexAt(run, insn) {
  const s = run.states;
  if (!s.length) return -1;
  let lo = 0, hi = s.length - 1, best = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (s[mid].insn <= insn) { best = mid; lo = mid + 1; } else { hi = mid - 1; }
  }
  return best;
}
function stateAt(run, insn) {
  const i = stateIndexAt(run, insn);
  return i >= 0 ? run.states[i] : null;
}

function eventIndexAt(run, insn) {
  const a = run.events.insn;
  let lo = 0, hi = a.length - 1, best = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (a[mid] <= insn) { best = mid; lo = mid + 1; } else { hi = mid - 1; }
  }
  return best;
}

function evGet(run, i) {
  const E = run.events, D = run.dict;
  return {
    i, insn: E.insn[i], cpu: E.cpu[i],
    kind: D.kinds[E.kind[i]], res: D.res[E.res[i]],
    pid: E.pid[i] < 0 ? null : E.pid[i],
    pc: E.pc[i], func: D.funcs[E.func[i]],
    entry: E.entry?.[i] === 1,
    entryName: E.entry_name?.[i] >= 0 ? D.funcs[E.entry_name[i]] : '',
    stack: E.stack?.[i]?.map((id) => D.funcs[id]) || null,
    tick: E.tick[i] < 0 ? null : E.tick[i],
    detail: E.detail[i], unknown: E.unknown[i],
  };
}

function functionName(run, id, full = false) {
  return (full ? run.dict.full_funcs?.[id] : null) || run.dict.funcs[id] || '';
}

function compactFunction(name) {
  // Keep trait and generic syntax intact; shorten plain namespace paths only.
  if (/[<>]/.test(name)) return name;
  return name.split('::').slice(-2).join('::');
}

function functionParts(name) {
  const parts = []; let start = 0, depth = 0;
  for (let i = 0; i < name.length; i++) {
    if ('<(['.includes(name[i])) depth++;
    else if ('>)]'.includes(name[i]) && !(name[i] === '>' && name[i - 1] === '-')) depth = Math.max(0, depth - 1);
    else if (depth === 0 && name.slice(i, i + 2) === '::') {
      parts.push(name.slice(start, i)); start = i + 2; i++;
    }
  }
  parts.push(name.slice(start)); return parts.filter(Boolean);
}

function sourceFrames(run, i) {
  const E = run.events;
  let ids = E.stack?.[i]?.length ? E.stack[i] : [E.entry_name?.[i] >= 0 ? E.entry_name[i] : E.func[i]];
  let pcs = E.stack_pc?.[i] || [E.pc[i]];
  if (ids.length === 1 && E.caller?.[i] >= 0) {
    ids = [E.caller[i], ...ids]; pcs = [E.caller_pc?.[i] || 0, ...pcs];
  }
  return ids.map((id, k) => {
    const pc = pcs[k] || 0;
    const name = functionName(run, id, true) || run.source?.locations?.[hex(pc)]?.[0]?.function || '';
    return {id, pc, name, label: compactFunction(functionName(run, id) || name)};
  }).reverse();
}

function renderDebugger(run, i, host, navigate) {
  host.replaceChildren();
  const frames = sourceFrames(run, i);
  const toolbar = el('div', 'debug-toolbar');
  const label = el('strong', null, `CPU ${run.events.cpu[i]} · ${fmtInsn(run.events.insn[i])}`);
  toolbar.appendChild(label);
  if (navigate) {
    for (const [delta, text] of [[-1, '上一事件'], [1, '下一事件']]) {
      const button = el('button', 'secondary-control', text);
      button.type = 'button'; button.disabled = !navigate.available(delta);
      button.dataset.debugNav = String(delta);
      button.onclick = () => navigate.go(delta); toolbar.appendChild(button);
    }
  }
  host.appendChild(toolbar);
  const body = el('div', 'debug-body');
  const stack = el('section', 'debug-stack');
  stack.setAttribute('aria-label', '调用栈');
  stack.appendChild(el('h3', null, run.events.stack?.[i]?.length > 1 ? '调用栈'
    : frames.length > 1 ? '调用位置' : '当前函数'));
  const list = el('div', 'debug-frames'); list.setAttribute('role', 'listbox'); list.setAttribute('aria-label', '选择栈帧');
  stack.appendChild(list);
  const editor = el('section', 'debug-editor'); editor.setAttribute('aria-label', '源码');
  const splitter = el('div', 'debug-splitter'); splitter.tabIndex = 0;
  splitter.setAttribute('role', 'separator'); splitter.setAttribute('aria-label', '调整调用栈大小');
  const vertical = () => getComputedStyle(body).flexDirection === 'column';
  const resize = value => {
    const isVertical = vertical();
    const max = (isVertical ? body.clientHeight : body.clientWidth) * 0.5;
    const size = Math.max(90, Math.min(max, value));
    stack.style[isVertical ? 'height' : 'width'] = `${size}px`;
    splitter.setAttribute('aria-valuenow', String(Math.round(size)));
    splitter.setAttribute('aria-valuemin', '90'); splitter.setAttribute('aria-valuemax', String(Math.round(max)));
  };
  splitter.setAttribute('aria-orientation', vertical() ? 'horizontal' : 'vertical');
  splitter.onkeydown = event => {
    if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) return;
    event.preventDefault();
    event.stopPropagation();
    resize((vertical() ? stack.clientHeight : stack.clientWidth) +
      (['ArrowLeft', 'ArrowUp'].includes(event.key) ? -20 : 20));
  };
  splitter.onpointerdown = event => {
    if (event.button !== 0) return;
    event.preventDefault(); splitter.setPointerCapture(event.pointerId);
    const start = vertical() ? event.clientY : event.clientX;
    const size = vertical() ? stack.clientHeight : stack.clientWidth;
    splitter.onpointermove = move => resize(size + (vertical() ? move.clientY : move.clientX) - start);
    splitter.onpointerup = () => { splitter.onpointermove = null; };
    splitter.onlostpointercapture = () => { splitter.onpointermove = null; };
  };
  body.append(stack, splitter, editor); host.appendChild(body);
  const views = el('div', 'debug-mobile-views');
  const switchView = value => {
    host.dataset.mobileView = value;
    for (const button of views.children) button.setAttribute('aria-pressed', String(button.dataset.view === value));
  };
  for (const [value, text] of [['stack', '调用栈'], ['source', '源码']]) {
    const button = el('button', 'secondary-control', text); button.type = 'button';
    button.dataset.view = value; button.onclick = () => switchView(value); views.appendChild(button);
  }
  host.insertBefore(views, body); switchView('source');
  requestAnimationFrame(() => {
    splitter.setAttribute('aria-orientation', vertical() ? 'horizontal' : 'vertical');
    splitter.setAttribute('aria-valuenow', String(vertical() ? stack.clientHeight : stack.clientWidth));
    splitter.setAttribute('aria-valuemin', '90');
    splitter.setAttribute('aria-valuemax', String(Math.round((vertical() ? body.clientHeight : body.clientWidth) / 2)));
  });
  const buttons = [];
  function selectFrame(index) {
    if (NF.sourceSelection.event !== i || NF.sourceSelection.frame !== index)
      NF.sourceSelection = {event: i, frame: index, inline: -1};
    buttons.forEach((b, k) => { b.setAttribute('aria-selected', String(k === index)); b.tabIndex = k === index ? 0 : -1; });
    const frame = frames[index];
    editor.replaceChildren();
    const full = el('div', 'debug-symbol', frame.name || '未解析的函数'); full.title = frame.name;
    editor.appendChild(full);
    const tools = el('div', 'source-toolbar');
    const raw = run.dict.raw_funcs?.[frame.id];
    if (raw) {
      const original = el('details', 'debug-original');
      original.appendChild(el('summary', null, '原始符号'));
      original.appendChild(el('pre', null, raw)); editor.appendChild(original);
    }
    const copy = el('button', 'secondary-control', '复制符号'); copy.type = 'button'; copy.disabled = !raw;
    copy.title = raw || '原始符号未保存';
    copy.onclick = async () => {
      try { await navigator.clipboard.writeText(raw); copy.textContent = '已复制'; }
      catch { copy.textContent = '复制失败'; }
    };
    const locations = run.source?.locations?.[hex(frame.pc)] || [];
    const locationSelect = el('select'); locationSelect.setAttribute('aria-label', '源码位置与内联函数');
    locations.forEach((loc, k) => locationSelect.appendChild(new Option(`${loc.function || frame.name} · ${loc.path.split(/[\\/]/).pop()}:${loc.line}`, String(k))));
    if (locations.length > 1) tools.appendChild(locationSelect);
    tools.appendChild(copy); editor.appendChild(tools);
    const content = el('div', 'source-content'); editor.appendChild(content);
    function showLocation(k) {
      content.replaceChildren();
      const loc = locations[k];
      const file = loc?.file != null ? run.source?.files?.[loc.file] : null;
      const path = el('div', 'source-path', loc ? `${file?.path || loc.path}:${loc.line}` : '源码位置未记录');
      path.title = loc?.path || ''; content.appendChild(path);
      if (!file) {
        const message = {size_limit: '源码文件超过嵌入大小限制。', read_error: '源码文件无法读取。'}[loc?.file_status];
        content.appendChild(el('p', 'source-empty', message || (loc ? '源码未嵌入此报告。' : '此地址没有源码行信息。')));
        return;
      }
      const controls = el('div', 'source-controls');
      const toolsToggle = el('button', 'secondary-control source-tools-toggle', '查找与行号');
      toolsToggle.type = 'button'; toolsToggle.setAttribute('aria-expanded', 'false');
      toolsToggle.onclick = () => toolsToggle.setAttribute('aria-expanded', String(content.classList.toggle('source-tools-open')));
      content.appendChild(toolsToggle);
      const find = el('input'); find.type = 'search'; find.placeholder = '在文件中查找'; find.setAttribute('aria-label', '在源码文件中查找');
      const next = el('button', 'secondary-control', '下一个'); next.type = 'button';
      const jump = el('input'); jump.type = 'number'; jump.min = '1'; jump.placeholder = '行号'; jump.setAttribute('aria-label', '跳转到行');
      const current = el('button', 'secondary-control', '当前位置'); current.type = 'button';
      const status = el('span', 'source-find-status'); status.setAttribute('role', 'status');
      controls.append(find, next, jump, current, status); content.appendChild(controls);
      const code = el('div', 'source-code'); code.tabIndex = 0; code.setAttribute('aria-label', file.path);
      const lines = file.text.split('\n'); jump.max = String(lines.length);
      let highlighted = null;
      const extension = file.path.split('.').pop().toLowerCase();
      const language = {rs: 'rust', c: 'c', h: 'c', cc: 'cpp', cpp: 'cpp', hpp: 'cpp'}[extension];
      if (language && file.text.length < 500000 && typeof NFHighlight !== 'undefined') {
        const template = document.createElement('template');
        template.innerHTML = NFHighlight.highlight(file.text, {language, ignoreIllegals: true}).value;
        // Split the token tree into lines, preserving multiline comment styles.
        highlighted = [document.createDocumentFragment()];
        function split(node, classes = []) {
          if (node.nodeType === Node.TEXT_NODE) {
            node.textContent.split('\n').forEach((part, k) => {
              if (k) highlighted.push(document.createDocumentFragment());
              const token = el('span', classes.join(' '), part);
              highlighted[highlighted.length - 1].appendChild(token);
            });
          } else for (const child of node.childNodes) split(child, [...classes, ...node.classList]);
        }
        for (const node of template.content.childNodes) split(node);
      }
      // Render a bounded window even for very large generated files.
      let center = loc.line, match = -1;
      function paint(line) {
        center = Math.max(1, Math.min(lines.length, Number(line) || 1));
        code.replaceChildren();
        const start = Math.max(1, center - 100), end = Math.min(lines.length, center + 150);
        if (start > 1) {
          const more = el('button', 'source-more', '向上查看'); more.type = 'button'; more.onclick = () => paint(start - 50); code.appendChild(more);
        }
        for (let n = start; n <= end; n++) {
          const row = el('div', 'source-line'); row.dataset.line = String(n);
          if (n === loc.line) row.classList.add('source-current');
          if (n === match + 1) row.classList.add('source-match');
          row.appendChild(el('span', 'source-line-number', String(n)));
          const text = el('code');
          if (highlighted?.[n - 1]) text.appendChild(highlighted[n - 1].cloneNode(true));
          else text.textContent = lines[n - 1] || ' ';
          row.appendChild(text); code.appendChild(row);
        }
        if (end < lines.length) {
          const more = el('button', 'source-more', '向下查看'); more.type = 'button'; more.onclick = () => paint(end + 50); code.appendChild(more);
        }
        requestAnimationFrame(() => {
          const row = code.querySelector(`[data-line="${center}"]`);
          if (row) code.scrollTop = Math.max(0, code.scrollTop +
            row.getBoundingClientRect().top - code.getBoundingClientRect().top - code.clientHeight / 3);
        });
      }
      function findNext() {
        const q = find.value.toLowerCase(); if (!q) return;
        const start = match + 1;
        match = lines.findIndex((text, n) => n >= start && text.toLowerCase().includes(q));
        if (match < 0) match = lines.findIndex(text => text.toLowerCase().includes(q));
        status.textContent = match < 0 ? '没有匹配项' : `第 ${match + 1} 行`;
        if (match >= 0) paint(match + 1);
      }
      find.oninput = () => { match = -1; };
      find.onkeydown = event => { if (event.key === 'Enter') { event.preventDefault(); findNext(); } };
      next.onclick = findNext;
      jump.onkeydown = event => { if (event.key === 'Enter') { event.preventDefault(); paint(jump.value); } };
      current.onclick = () => paint(loc.line);
      content.appendChild(code); paint(loc.line);
    }
    const preferred = Math.max(0, locations.findIndex(location => location.file != null));
    const inline = NF.sourceSelection.inline < 0 ? preferred
      : Math.min(NF.sourceSelection.inline, Math.max(0, locations.length - 1));
    locationSelect.value = String(inline);
    locationSelect.onchange = () => {
      NF.sourceSelection.inline = Number(locationSelect.value);
      showLocation(NF.sourceSelection.inline);
    };
    showLocation(inline);
  }
  frames.forEach((frame, index) => {
    const button = el('button', 'debug-frame'); button.type = 'button'; button.setAttribute('role', 'option');
    button.title = frame.name;
    button.appendChild(el('span', 'frame-number', String(index)));
    button.appendChild(el('span', 'frame-name', frame.label || compactFunction(frame.name) || hex(frame.pc)));
    button.onclick = () => {
      selectFrame(index); switchView('source');
      host.dispatchEvent(new CustomEvent('source-frame-selected'));
      if (window.matchMedia('(max-width: 850px)').matches) editor.querySelector('.source-code')?.focus({preventScroll: true});
    };
    button.onkeydown = event => {
      let target = index;
      if (event.key === 'ArrowDown') target = Math.min(frames.length - 1, index + 1);
      else if (event.key === 'ArrowUp') target = Math.max(0, index - 1);
      else if (event.key === 'Home') target = 0;
      else if (event.key === 'End') target = frames.length - 1;
      else return;
      event.preventDefault(); selectFrame(target); buttons[target].focus();
    };
    buttons.push(button); list.appendChild(button);
  });
  if (frames.length) selectFrame(NF.sourceSelection.event === i ? Math.min(NF.sourceSelection.frame, frames.length - 1) : 0);
}

function eventGroup(kind) {
  if (/^(syscall|sbi)\./.test(kind)) return '系统调用';
  if (/^(trap|interrupt|firmware)\./.test(kind)) return '异常与中断';
  if (/^(disk|bcache|inode|log)\./.test(kind)) return '文件与 I/O';
  if (/^(phys|pagetable|vm)\./.test(kind)) return '内存与页表';
  if (/^(sched|proc|sync)\./.test(kind)) return '进程与同步';
  if (/^func\./.test(kind)) return '函数入口';
  return '其他';
}
function eventLabel(e) {
  return e.kind.startsWith('func.') ? '函数入口' : e.kind;
}


const KIND_COLOR = {
  0: [22, 27, 34],     // free
  1: [70, 78, 92],     // kernel-image
  2: [104, 116, 136],  // kernel-other
  3: [74, 163, 255],   // user
  4: [210, 153, 34],   // pagetable
  5: [163, 113, 247],  // trapframe
  6: [86, 122, 180],   // kstack
  7: [63, 185, 80],    // user-shared（COW 的典型形态）
  8: [40, 46, 58],     // unknown
};
const KIND_LABEL = {
  0: '空闲', 1: '内核镜像', 2: '内核动态', 3: '用户页',
  4: '页表页', 5: 'trapframe', 6: '内核栈', 7: '多进程共享', 8: '未知',
};

const KIND_DEF = {
  0: '未分配',
  1: '内核代码 / 静态数据',
  2: '内核运行时分配',
  3: '单进程用户页',
  4: '页表节点',
  5: 'trapframe',
  6: '内核栈',
  7: '多进程共享',
  8: '归属未知',
};

function pidTint(rgb, pid) {
  if (!pid) return rgb;
  const h = (pid * 2654435761) % 360;
  const f = 0.55 + 0.45 * (((h % 97) / 97));
  const g = 0.55 + 0.45 * (((h % 61) / 61));
  return [Math.min(255, rgb[0] * f), Math.min(255, rgb[1] * g), rgb[2]];
}

function expandPhys(state) {
  const total = state.total;
  const kind = new Uint8Array(total);
  const pid = new Int32Array(total);
  let p = 0;
  for (const [k, pd, n] of state.phys) {
    for (let i = 0; i < n && p < total; i++, p++) { kind[p] = k; pid[p] = pd; }
  }
  return { kind, pid };
}

function physRowPlan(state, cols, prevState) {
  const rows = Math.ceil(state.total / cols);
  const { kind } = expandPhys(state);
  const prev = prevState && prevState.total === state.total
    ? expandPhys(prevState).kind : null;

  const busy = new Uint8Array(rows);
  for (let r = 0; r < rows; r++) {
    for (let i = r * cols; i < Math.min(state.total, (r + 1) * cols); i++) {
      if (kind[i] !== 0 || (prev && prev[i] !== 0)) { busy[r] = 1; break; }
    }
  }
  const keep = new Uint8Array(rows);
  for (let r = 0; r < rows; r++) {
    if (!busy[r]) continue;
    for (let d = -1; d <= 1; d++) { const q = r + d; if (q >= 0 && q < rows) keep[q] = 1; }
  }

  const plan = [];
  let r = 0;
  while (r < rows) {
    if (keep[r]) { plan.push({ type: 'data', r }); r++; continue; }
    let e = r;
    while (e < rows && !keep[e]) e++;
    if (e - r >= 3) { plan.push({ type: 'gap', from: r, to: e - 1 }); }
    else for (let q = r; q < e; q++) plan.push({ type: 'data', r: q });
    r = e;
  }
  return { plan, rows };
}

function drawPhys(canvas, state, highlightPid, prevState) {
  const cols = 256;
  const total = state.total;
  const { kind, pid } = expandPhys(state);
  const prev = prevState && prevState.total === total ? expandPhys(prevState) : null;

  const plan = canvas._nffold === false
    ? { plan: Array.from({ length: Math.ceil(total / cols) }, (_, r) => ({ type: 'data', r })) }
    : physRowPlan(state, cols, prevState);
  const lines = plan.plan;

  canvas.width = cols; canvas.height = lines.length;
  const ctx = canvas.getContext('2d');
  const img = ctx.createImageData(cols, lines.length);
  let changed = 0;

  for (let y = 0; y < lines.length; y++) {
    const ln = lines[y];
    if (ln.type === 'gap') {
      for (let x = 0; x < cols; x++) {
        const o = (y * cols + x) * 4;
        img.data[o] = 12; img.data[o + 1] = 14; img.data[o + 2] = 18; img.data[o + 3] = 255;
      }
      continue;
    }
    for (let x = 0; x < cols; x++) {
      const i = ln.r * cols + x;
      const o = (y * cols + x) * 4;
      if (i >= total) { img.data[o + 3] = 255; continue; }
      let c = KIND_COLOR[kind[i]] || KIND_COLOR[8];
      if (kind[i] === 3 || kind[i] === 7) c = pidTint(c, pid[i]);
      let dim = 1;
      if (highlightPid && pid[i] !== highlightPid && (kind[i] === 3 || kind[i] === 7)) dim = 0.35;
      else if (highlightPid && kind[i] !== 3 && kind[i] !== 7) dim = 0.4;
      let r = c[0] * dim, g = c[1] * dim, b = c[2] * dim;
      if (prev && (prev.kind[i] !== kind[i] || prev.pid[i] !== pid[i])) {
        changed++;
        if (kind[i] === 0) { r = 74; g = 32; b = 36; }
        else { r += (255 - r) * 0.38; g += (255 - g) * 0.38; b += (255 - b) * 0.38; }
      }
      img.data[o] = r; img.data[o + 1] = g; img.data[o + 2] = b; img.data[o + 3] = 255;
    }
  }
  ctx.putImageData(img, 0, 0);
  canvas._nfphys = { kind, pid, cols, total, lines };
  return changed;
}


function drawMinimap(run) {
  const c = $('#minimap');
  const w = c.clientWidth || 900, h = 34;
  c.width = w; c.height = h;
  const ctx = c.getContext('2d');
  ctx.fillStyle = '#161b22'; ctx.fillRect(0, 0, w, h);
  const total = run.meta.total_insns || 1;

  const bins = new Uint32Array(w);
  const E = run.events.insn;
  for (let i = 0; i < E.length; i++) {
    const x = Math.min(w - 1, Math.floor((E[i] / total) * w));
    bins[x]++;
  }
  let max = 1;
  for (const v of bins) if (v > max) max = v;
  ctx.fillStyle = '#2d4f7c';
  for (let x = 0; x < w; x++) {
    const hgt = Math.round((bins[x] / max) * (h - 8));
    if (hgt > 0) ctx.fillRect(x, h - hgt - 4, 1, hgt);
  }

  ctx.fillStyle = '#3fb950';
  for (const s of run.states) {
    const x = Math.floor((s.insn / total) * w);
    ctx.fillRect(x, 0, 1, 4);
  }

  const marks = { 'kernel.panic': '#f85149', 'trap.page_fault': '#d29922' };
  for (let i = 0; i < E.length; i++) {
    const k = run.dict.kinds[run.events.kind[i]];
    const col = marks[k];
    if (col) {
      const x = Math.floor((E[i] / total) * w);
      ctx.fillStyle = col; ctx.fillRect(x, h - 4, 1, 4);
    }
  }

  const ps = run.meta.program_start_insn;
  if (ps) {
    const x = Math.floor((ps / total) * w);
    ctx.fillStyle = '#a371f7';
    ctx.fillRect(x, 0, 1, h);
    ctx.fillStyle = '#a371f7'; ctx.font = '9px sans-serif';
    ctx.fillText('程序开始', Math.min(w - 48, x + 3), 10);
  }

  const px = Math.floor((NF.cur / total) * w);
  ctx.fillStyle = '#4aa3ff';
  ctx.fillRect(px, 0, 1, h);
}


function axisNum(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return '—';
  const a = Math.abs(n);
  if (a >= 1e9) return `${(n / 1e9).toFixed(a >= 1e10 ? 0 : 1)}G`;
  if (a >= 1e6) return `${(n / 1e6).toFixed(a >= 1e7 ? 0 : 1)}M`;
  if (a >= 1e3) return `${(n / 1e3).toFixed(a >= 1e4 ? 0 : 1)}K`;
  return Number.isInteger(n) ? n.toLocaleString('en-US') : n.toFixed(1);
}

function drawChart(canvas, series, opts) {
  opts = opts || {};
  const w = canvas.clientWidth || 600, h = canvas.clientHeight || 130;
  canvas.width = w; canvas.height = h;
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = '#161b22'; ctx.fillRect(0, 0, w, h);
  const margin = { left: 52, right: 12, top: 22, bottom: 25 };
  const plotW = Math.max(10, w - margin.left - margin.right);
  const plotH = Math.max(10, h - margin.top - margin.bottom);
  let maxY = 0;
  const okPt = (p) => p && p[1] !== null && p[1] !== undefined && Number.isFinite(Number(p[1]));
  for (const s of series) for (const p of s.points) {
    if (okPt(p)) maxY = Math.max(maxY, Number(p[1]));
  }
  maxY = Math.max(1, maxY);
  const minX = Number.isFinite(Number(opts.xMin)) ? Number(opts.xMin) : 0;
  const fallbackX = Math.max(...series.flatMap((s) => s.points.filter((p) => p && p[0] !== null).map((p) => Number(p[0]))), 1);
  const maxX = Number.isFinite(Number(opts.xMax)) ? Number(opts.xMax) : fallbackX;
  const spanX = Math.max(1, maxX - minX);
  const xPos = (x) => margin.left + ((Number(x) - minX) / spanX) * plotW;
  const yPos = (y) => margin.top + plotH - (Number(y) / maxY) * plotH;

  ctx.font = '10px monospace';
  ctx.textBaseline = 'middle';
  ctx.fillStyle = '#8b98a8';
  ctx.textAlign = 'left';
  ctx.fillText(opts.title || '', margin.left, 10);
  ctx.textAlign = 'right';
  ctx.fillText(`峰值 ${axisNum(maxY)}`, w - margin.right, 10);

  ctx.strokeStyle = '#2a3140'; ctx.lineWidth = 1;
  ctx.fillStyle = '#8b98a8';
  for (let i = 0; i <= 4; i++) {
    const y = margin.top + (plotH * i) / 4;
    ctx.beginPath(); ctx.moveTo(margin.left, y); ctx.lineTo(w - margin.right, y); ctx.stroke();
    ctx.textAlign = 'right'; ctx.fillText(axisNum(maxY * (1 - i / 4)), margin.left - 7, y);
  }
  for (let i = 0; i <= 4; i++) {
    const x = margin.left + (plotW * i) / 4;
    ctx.beginPath(); ctx.moveTo(x, margin.top); ctx.lineTo(x, margin.top + plotH); ctx.stroke();
    ctx.textAlign = i === 0 ? 'left' : i === 4 ? 'right' : 'center';
    ctx.fillText(axisNum(minX + (spanX * i) / 4), x, h - 12);
  }
  ctx.strokeStyle = '#657384';
  ctx.beginPath(); ctx.moveTo(margin.left, margin.top); ctx.lineTo(margin.left, margin.top + plotH);
  ctx.lineTo(w - margin.right, margin.top + plotH); ctx.stroke();

  for (const s of series) {
    ctx.strokeStyle = s.color; ctx.lineWidth = 1.5; ctx.beginPath();
    let pen = false;
    for (const p of s.points) {
      if (!okPt(p)) { pen = false; continue; }
      const x = xPos(p[0]);
      const y = yPos(p[1]);
      if (x < margin.left || x > w - margin.right) { pen = false; continue; }
      pen ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
      pen = true;
    }
    ctx.stroke();
  }
  const px = xPos(NF.cur);
  if (px >= margin.left && px <= w - margin.right) {
    ctx.strokeStyle = '#4aa3ff'; ctx.lineWidth = 1; ctx.beginPath();
    ctx.moveTo(px, margin.top); ctx.lineTo(px, margin.top + plotH); ctx.stroke();
  }
}


function renderHeader() {
  const run = NF.runs[0];
  const m = run.meta;
  const box = $('#hmeta');
  box.innerHTML = '';
  const add = (k, v) => {
    const d = el('div');
    d.appendChild(el('span', null, k + ' '));
    d.appendChild(el('b', null, v));
    box.appendChild(d);
  };
  add('运行', m.run || '—');
  add('程序', m.program || '—');
  add('内核', (m.kernel_dir || '').split(/[\\/]/).pop() || '—');
  if (m.kernel_elf_sha256) add('ELF', m.kernel_elf_sha256.slice(0, 12));
  if (m.lab_stage !== null && m.lab_stage !== undefined) add('LAB_STAGE', String(m.lab_stage));
  if (m.make_vars && Object.keys(m.make_vars).length) {
    add('构建参数', Object.entries(m.make_vars).map(([a, b]) => `${a}=${b}`).join(' '));
  }
  add('CPU', String(m.cpus));
  add('总指令', fmtInsn(m.total_insns));
  add('快照', String(run.states.length));
  add('事件', String(run.events.insn.length));

  const b = $('#outcome');
  b.className = 'badge ' + (m.outcome || 'unknown');
  b.textContent = {
    completed: '程序正常结束', panic: '内核 panic', timeout: '运行超时',
    boot_failed: '启动失败', qemu_exited: 'QEMU 退出',
  }[m.outcome] || m.outcome;
}

function renderCapability() {
  const run = NF.runs[0];
  const c = run.meta.capability;
  const box = $('#capability');
  const items = [];
  if (!run.meta.kernel_elf_sha256) items.push('ELF 校验信息缺失');
  if (c.nftrace_records) items.push(`内核事件 ${num(c.nftrace_records)} 条`);
  if (c.missing_watch_functions && c.missing_watch_functions.length) {
    items.push(`未匹配的函数观察点 ${num(c.missing_watch_functions.length)} 个：${c.missing_watch_functions.slice(0, 4).join('、')}${c.missing_watch_functions.length > 4 ? '…' : ''}`);
  }
  if (c.missing_layout_fields && c.missing_layout_fields.length) {
    items.push(`未匹配的结构字段 ${num(c.missing_layout_fields.length)} 个`);
  }
  if (c.trace_truncated_at_eof) items.push('运行轨迹不完整');
  if (c.plugin_truncated) items.push('物理内存快照不完整');
  if (run.meta.event_selection && run.meta.event_selection.dropped) {
    const s = run.meta.event_selection;
    items.push(`事件浏览器显示 ${num(s.retained)} / ${num(s.raw)} 条`);
  }
  for (const [kind, d] of Object.entries(c.absent_declared || {})) {
    const why = d.why === 'feature' ? '本内核没有' : '缺少对应粒度的观察点';
    items.push(`${kind}：${why}`);
  }
  for (const wn of run.meta.warnings || []) items.push(`指令 ${fmtInsn(wn.insn)}：${shortText(wn.text, 140)}`);

  const cov = c.coverage || null;
  const metric = cov && cov.metrics;
  const complete = cov && cov.status === 'complete';
  const headline = cov
    ? `观测项 ${metric.covered}/${metric.applicable}`
      + (complete ? '' : ` · ${num((cov.blockers || []).length)} 项待检查`)
    : '采集信息';

  box.style.display = 'flex';
  box.className = 'capability ' + (complete ? 'coverage-complete' : 'coverage-incomplete');
  box.innerHTML = '';
  if (cov && cov.blockers && cov.blockers.length) {
    items.push(`待检查：${cov.blockers.map((b) => b.check).join('、')}`);
  }
  if (!items.length) {
    box.appendChild(el('span', 'cap-headline', headline));
    return;
  }
  const disclosure = el('details', 'cap-disclosure');
  const summary = el('summary');
  summary.appendChild(el('span', 'cap-headline', headline));
  summary.appendChild(el('span', 'cap-more', '查看采集信息'));
  disclosure.appendChild(summary);
  const ul = el('ul');
  for (const t of items) ul.appendChild(el('li', null, t));
  disclosure.appendChild(ul);
  box.appendChild(disclosure);
}

function renderTime() {
  const run = NF.runs[0];
  const total = run.meta.total_insns || 1;
  $('#slider').max = String(total);
  $('#slider').value = String(NF.cur);
  const miniStart = $('#mini-start');
  const miniEnd = $('#mini-end');
  if (miniStart) miniStart.textContent = '0';
  if (miniEnd) miniEnd.textContent = fmtInsn(total);
  const st = stateAt(run, NF.cur);
  const si = stateIndexAt(run, NF.cur);
  $('#tlabel').innerHTML =
    `指令 <b>${fmtInsn(NF.cur)}</b> / ${fmtInsn(total)} &nbsp; ` +
    `tick <b>${st && st.tick !== null ? st.tick : '—'}</b> &nbsp; ` +
    `快照 <b>${si >= 0 ? si + 1 : '—'}</b>/${run.states.length}`;
  drawMinimap(run);
}

function renderOverview() {
  const run = NF.runs[0];
  const m = run.metrics, st = stateAt(run, NF.cur);
  const p = $('#panel-overview');
  p.innerHTML = '';

  const cards = el('div', 'cards');
  const card = (v, l, s) => {
    const c = el('div', 'card');
    c.appendChild(el('div', 'v', v));
    c.appendChild(el('div', 'l', l));
    if (s) c.appendChild(el('div', 's', s));
    cards.appendChild(c);
  };
  const smet = (m.sampling || {}).metrics || {};
  const tagOf = (name) => {
    const r = smet[name];
    if (!r || !r.length) return '';
    const hi = r.filter((x) => x > 1);
    if (!hi.length) return '';
    return ` · ${r.some((x) => x <= 1) ? '部分' : ''}抽样 1/${hi.join('、1/')}`;
  };
  const hiRate = (name) => {
    const r = smet[name];
    if (!r || !r.length) return 0;
    const hi = Math.max(...r);
    return hi > 1 ? hi : 0;
  };
  const rate = (n, name) => {
    // A sampled count supports bounds, not an exact event frequency.
    const hi = name ? hiRate(name) : 0;
    if (hi) return `实际 ${num(n)}～${num(n * hi)} 次`;
    if (!n || !m.total_insns) return '';
    const per = m.total_insns / n;
    const fmt = per >= 1e6 ? (per / 1e6).toFixed(1) + 'M'
              : per >= 1e3 ? (per / 1e3).toFixed(1) + 'K' : per.toFixed(0);
    return `平均每 ${fmt} 条指令一次`;
  };
  card(fmtInsn(m.total_insns), '总指令数', '运行全程');
  card(num(m.syscalls), '系统调用', rate(m.syscalls));
  card(num(m.page_faults), '缺页异常', rate(m.page_faults));
  card(num(m.context_switches), '上下文切换' + tagOf('context_switches'),
       rate(m.context_switches, 'context_switches'));
  card(num(m.timer_interrupts + m.external_interrupts), '中断',
       `时钟 ${m.timer_interrupts} / 设备 ${m.external_interrupts}`);
  // Subtraction is defined only when both operands are complete observations.
  const ka = hiRate('kalloc'), kf = hiRate('kfree');
  const netUnknown =
    (m.kalloc === null || m.kfree === null) ? '净分配未知（没有观测点）'
    : (ka || kf)
      ? `样本 ${num(m.kalloc)}～${num(m.kalloc * (ka || 1))}`
        + ` / ${num(m.kfree)}～${num(m.kfree * (kf || 1))}`
    : `净 ${num(m.kalloc - m.kfree)} 页`;
  card(num(m.kalloc) + ' / ' + num(m.kfree), 'kalloc / kfree' + tagOf('kalloc'),
       netUnknown);
  card(num(m.disk_io), '磁盘 I/O' + tagOf('disk_io'), rate(m.disk_io, 'disk_io'));
  // Independently sampled counts do not determine a cache-hit ratio.
  const hrSampled = !!(hiRate('bcache_reads') || hiRate('disk_io'));
  const hrSub = m.cache_hit_accounting === 'unverified'
    ? `缓存请求 ${num(m.bcache_reads)} · 磁盘 I/O ${num(m.disk_io)}`
    : hrSampled ? '样本不可合并' : `${num(m.bcache_hits)} / ${num(m.bcache_reads)} 次缓存请求`;
  card((m.bcache_hit_rate == null || hrSampled)
         ? '—' : (m.bcache_hit_rate * 100).toFixed(1) + '%',
       '缓存命中率', hrSub);
  const withRange = (sub, n, name) => {
    const hi = hiRate(name);
    if (!hi || n === null || n === undefined) return sub;
    const r = `实际 ${num(n)}～${num(n * hi)} 次`;
    return sub ? `${sub} · ${r}` : r;
  };
  card(num(m.vm_maps), '映射区域' + tagOf('vm_maps'),
       withRange('一次 / 段', m.vm_maps, 'vm_maps'));
  card(num(m.page_table_maps), '页表项' + tagOf('page_table_maps'),
       withRange('一次 / PTE', m.page_table_maps, 'page_table_maps'));
  card(num(m.log_commits), '日志提交' + tagOf('log_commits'),
       withRange('', m.log_commits, 'log_commits'));
  const runStats = el('details', 'run-stats');
  runStats.appendChild(el('summary', null, '运行统计'));
  runStats.appendChild(cards);
  if (m.unobservable_reason) {
    const d = el('details', 'inline-disclosure hint');
    d.appendChild(el('summary', null, '指标不可用'));
    d.appendChild(el('div', 'disclosure-body', shortText(m.unobservable_reason, 90)));
    runStats.appendChild(d);
  }
  p.appendChild(runStats);

  p.appendChild(el('h3', null, '当前快照'));
  if (!st) {
    p.appendChild(el('div', 'hint', '没有快照。'));
  } else {
    const g = el('div', 'cards snapshot-summary');
    const c2 = (v, l) => {
      const c = el('div', 'card');
      c.appendChild(el('div', 'v', v)); c.appendChild(el('div', 'l', l));
      g.appendChild(c);
    };
    c2(num(st.free), '空闲物理页');
    c2(num(st.used), '已用物理页');
    c2(num(st.shared), '多进程共享页');
    const pOk = st.procs_ok !== false;
    const psum = (f) => (pOk ? st.procs.reduce((a, x) => a + f(x), 0) : null);
    c2(num(pOk ? st.procs.length : null), '活动进程');
    c2(num(psum((x) => x.user_pages)), '用户页合计');
    c2(num(psum((x) => x.cow_pages)), 'COW 标记页');
    p.appendChild(g);
    p.appendChild(renderProcTable(run, st));   // 解不出来时它自己会给出说明
  }

  p.appendChild(el('h3', null, '各核在执行什么'));
  p.appendChild(renderCpuLanes(run));
}

function renderProcTable(run, st) {
  if (st.procs_ok === false) {
    return el('div', 'err-box',
      '进程表不可用 · ' + shortText(st.procs_reason || '未知原因', 110));
  }
  // Keep decoded structural fields separate from manifest-defined fields.
  const structural = [
    ['slot', (p) => plain(p.slot), 'mono'],
    ['pid', (p) => plain(p.pid), null],
  ];
  if (st.procs.some((p) => run.dict.names[p.name])) {
    structural.push(['名字', (p) => run.dict.names[p.name] || '—', null]);
  }
  if (st.procs.some((p) => p.parent_pid !== null && p.parent_pid !== undefined)) {
    structural.push(['父进程', (p) => plain(p.parent_pid), null]);
  }
  const cols = [];
  const seen = new Map();
  for (const p of st.procs) {
    for (const k of Object.keys(p.fields || {})) {
      if (!seen.has(k)) seen.set(k, p.fields[k].role || null);
    }
  }
  const shownRoles = new Set(['id', 'name', 'state']);
  const fieldKeys = [...seen.keys()].filter((k) => !shownRoles.has(seen.get(k)));

  const dropped = [];
  const live = [];
  for (const k of fieldKeys) {
    const states = st.procs.map((p) => (p.fields || {})[k]).filter(Boolean);
    if (states.length && states.every((f) => f.state === 'absent')) {
      const why = states.find((f) => f.reason)?.reason || '未说明原因';
      dropped.push(`${k}：${why}`);
    } else {
      live.push(k);
    }
  }

  const t = el('table');
  const head = el('tr');
  for (const [label] of structural) head.appendChild(el('th', null, label));
  head.appendChild(el('th', null, '状态'));
  for (const lbl of ['用户页', 'COW 页', '页表页']) {
    head.appendChild(el('th', null, lbl));
  }
  for (const k of live) head.appendChild(el('th', null, k));
  t.appendChild(head);

  for (const p of st.procs) {
    const tr = el('tr', 'clickable');
    if (NF.selPid === p.pid) tr.className += ' sel';
    const td = (v, cls) => { tr.appendChild(el('td', cls, v)); };
    for (const [, get, cls] of structural) td(get(p), cls);
    const s = el('td');
    s.appendChild(el('span', 'tag st-' + p.state_name, p.state_name));
    tr.appendChild(s);
    td(plain(p.user_pages), 'mono');
    td(plain(p.cow_pages), 'mono');
    td(plain(p.pt_pages), 'mono');
    for (const k of live) tr.appendChild(fieldTd((p.fields || {})[k]));
    tr.onclick = () => {
      NF.selPid = NF.selPid === p.pid ? null : p.pid;
      render(); showProcDetail(run, st, p);
    };
    t.appendChild(tr);
  }

  if (!fieldKeys.length && st.procs.length) {
    const box = el('div');
    box.appendChild(t);
    box.appendChild(el('div', 'hint', '旧格式：仅显示通用字段。'));
    return box;
  }
  if (dropped.length) {
    const box = el('div');
    box.appendChild(t);
    const d = el('details', 'inline-disclosure hint');
    d.appendChild(el('summary', null, `未显示的可选字段（${dropped.length}）`));
    d.appendChild(el('div', 'disclosure-body',
      dropped.map((item) => item.split('：')[0]).join('、') + '：当前内核未提供'));
    box.appendChild(d);
    return box;
  }
  return t;
}

/* Manifest field states: present, empty, and absent. */
function fieldTd(f) {
  if (!f) return el('td', 'mono', '—');
  if (f.state === 'absent') {
    const d = el('td', 'mono', '—');
    if (f.reason) d.title = f.reason;
    return d;
  }
  if (f.state === 'empty') return el('td', 'mono', '（空）');
  const v = f.value;
  if (v === null || v === undefined) return el('td', 'mono', '—');
  if (Array.isArray(v)) {
    const n = v.filter((x) => x !== null && x !== undefined).length;
    const d = el('td', 'mono', n ? `${n} 项` : '（空）');
    d.title = JSON.stringify(v);
    return d;
  }
  // Address formatting follows the manifest reader and role, not magnitude.
  const r = f.reader || '';
  const ADDR_ROLES = ['sched_context', 'trap_context', 'address_space_root'];
  if (/ptr|ppn|addr/.test(r) || ADDR_ROLES.includes(f.role)) {
    return el('td', 'mono', typeof v === 'number' ? hex(v) : String(v));
  }
  if (typeof v === 'number') return el('td', 'mono', num(v));
  return el('td', 'mono', String(v));
}

function renderCpuLanes(run) {
  const wrap = el('div');
  const total = run.meta.total_insns || 1;
  const ncpu = run.meta.cpus;
  const S = run.samples;
  for (let c = 0; c < ncpu; c++) {
    const cv = el('canvas', 'chart');
    cv.style.height = '26px';
    wrap.appendChild(el('div', 'hint', `CPU ${c} · 用户 / 内核 / 无采样`));
    wrap.appendChild(cv);
    setTimeout(() => {
      const w = cv.clientWidth || 600, h = 26;
      cv.width = w; cv.height = h;
      const ctx = cv.getContext('2d');
      ctx.fillStyle = '#1c2230'; ctx.fillRect(0, 0, w, h);
      for (let i = 0; i < S.insn.length; i++) {
        if (S.cpu[i] !== c) continue;
        const x = Math.floor((S.insn[i] / total) * w);
        ctx.fillStyle = S.priv[i] === 0 ? '#3fb950' : '#4aa3ff';
        ctx.fillRect(x, 2, 1, h - 4);
      }
      const px = Math.floor((NF.cur / total) * w);
      ctx.fillStyle = 'oklch(98% .005 215)'; ctx.fillRect(px, 0, 1, h);
    }, 0);
  }
  const axis = el('div', 'cpu-axis');
  axis.appendChild(el('span', null, '0'));
  axis.appendChild(el('span', null, axisNum(total / 2)));
  axis.appendChild(el('span', null, axisNum(total)));
  wrap.appendChild(axis);
  return wrap;
}

function renderPhys() {
  const run = NF.runs[0];
  const p = $('#panel-phys');
  p.innerHTML = '';
  const st = stateAt(run, NF.cur);
  if (!st) { p.appendChild(el('div', 'hint', '该时刻没有物理内存快照。')); return; }
  if (!st.phys_ok) {
    p.appendChild(el('div', 'err-box',
      '物理内存不可用 · ' + shortText(st.phys_reason || '未知原因', 110)));
  }

  const base = run.meta.ram_base ?? 0x80000000;
  const psz = run.meta.page_size ?? 4096;
  const cols = 256;                       // 每行 256 页
  const rowBytes = cols * psz;            // 每行正好 1 MiB —— 这让地址刻度变得好读
  const rows = Math.ceil(st.total / cols);

  p.appendChild(el('div', 'hint',
    `每格 ${psz / 1024} KiB · 点击查看物理页` +
    (!st.pt_root_src ? ' · 无页表根观测' : '') +
    (st.phys_reason ? ` · ${shortText(st.phys_reason, 120)}` : '')));

  const legend = el('div', 'legend2');
  for (const k of [0, 1, 2, 3, 7, 4, 5, 6, 8]) {
    const s = el('div', 'lgitem');
    const i = el('i'); const c = KIND_COLOR[k];
    i.style.background = `rgb(${c[0]},${c[1]},${c[2]})`;
    s.appendChild(i);
    const t = el('div');
    t.appendChild(el('b', null, KIND_LABEL[k]));
    t.appendChild(el('span', 'lgdef', KIND_DEF[k] || ''));
    s.appendChild(t);
    legend.appendChild(s);
  }
  p.appendChild(legend);

  const bar = el('div', 'physopt');
  const cb = el('input'); cb.type = 'checkbox'; cb.id = 'foldchk';
  cb.checked = NF.foldPhys !== false;
  cb.onchange = () => { NF.foldPhys = cb.checked; renderPhys(); };
  const lb = el('label'); lb.htmlFor = 'foldchk';
  lb.textContent = '折叠空闲区域';
  bar.appendChild(cb); bar.appendChild(lb);
  p.appendChild(bar);

  const wrap = el('div', 'physwrap');
  const axis = el('div', 'physaxis');
  const cv = el('canvas'); cv.id = 'physcanvas';
  cv._nffold = NF.foldPhys !== false;
  wrap.appendChild(axis);
  wrap.appendChild(cv);
  p.appendChild(wrap);

  const si = stateIndexAt(run, NF.cur);
  const prevSt = si > 0 ? run.states[si - 1] : null;
  const changed = drawPhys(cv, st, NF.selPid, prevSt);

  const lines = cv._nfphys.lines;
  const minRows = Math.max(2, Math.ceil(lines.length / 14));
  let lastY = -999;
  for (let y = 0; y < lines.length; y++) {
    const ln = lines[y];
    const top = ((y + 0.5) / lines.length * 100) + '%';
    if (ln.type === 'gap') {
      const g = el('div', 'atick gap',
        `⋯ ${(ln.to - ln.from + 1) * rowBytes / 1048576} MiB 全空闲 ⋯`);
      g.style.top = top; axis.appendChild(g); lastY = y;
      continue;
    }
    if (y - lastY < minRows) continue;
    lastY = y;
    const lab = el('div', 'atick', '0x' + (base + ln.r * rowBytes).toString(16));
    lab.style.top = top; axis.appendChild(lab);
  }

  cv.onclick = (e) => {
    const r = cv.getBoundingClientRect();
    const x = Math.floor(((e.clientX - r.left) / r.width) * cv.width);
    const y = Math.floor(((e.clientY - r.top) / r.height) * cv.height);
    const ln = lines[y];
    if (!ln || ln.type !== 'data') return;      // 点在折叠分隔线上，没有对应的页
    const idx = ln.r * cv.width + x;
    if (idx >= 0 && idx < st.total) { NF.selPage = idx; showPageDetail(run, st, idx); }
  };

  const folded = lines.filter((l) => l.type === 'gap')
                      .reduce((a, l) => a + (l.to - l.from + 1), 0);
  if (prevSt || folded) p.appendChild(el('div', 'hint',
    [prevSt ? `变化 ${num(changed)} 页` : '', folded ? `折叠空闲 ${folded} 行` : '']
      .filter(Boolean).join(' · ')));

  const g = el('div', 'cards');
  const c2 = (v, l, sub) => {
    const c = el('div', 'card');
    c.appendChild(el('div', 'v', v));
    c.appendChild(el('div', 'l', l));
    if (sub) c.appendChild(el('div', 's', sub));
    g.appendChild(c);
  };
  const pct = (x) => ((x / st.total) * 100).toFixed(1) + '%';
  const mib = (x) => {
    const k = x * psz / 1024;
    return k >= 1024 ? (k / 1024).toFixed(1) + ' MiB' : num(k) + ' KiB';
  };
  const why = (reason) => shortText(reason || '未确定', 60);
  c2(num(st.used), '已用物理页',
     st.used === null ? why(st.phys_reason)
                      : `${pct(st.used)}　${mib(st.used)}` + deltaStr(prevSt, st, 'used'));
  c2(num(st.free), '空闲物理页',
     st.free === null ? why(st.phys_reason) : `${pct(st.free)}　${mib(st.free)}`);
  c2(num(st.shared), '多进程共享页',
     st.shared === null ? why(st.procs_reason)
     : st.shared ? `${pct(st.shared)}　${mib(st.shared)}`
                 : '0 页共享');
  c2(num(st.total), '物理页总数', `${mib(st.total)}　每页 ${psz / 1024} KiB`);
  p.appendChild(g);
}

function deltaStr(prev, cur, field) {
  if (!prev) return '';
  if (prev[field] === null || cur[field] === null) return '';
  const d = cur[field] - prev[field];
  if (!d) return '　Δ 0';
  return `　Δ ${d > 0 ? '+' : ''}${num(d)}`;
}

function renderProcs() {
  const run = NF.runs[0];
  const p = $('#panel-procs');
  p.innerHTML = '';
  const st = stateAt(run, NF.cur);
  if (!st) { p.appendChild(el('div', 'hint', '该时刻没有快照。')); return; }

  p.appendChild(el('h3', null, '进程表'));
  p.appendChild(renderProcTable(run, st));

  if (st.cpus.length) {
    p.appendChild(el('h3', null, '各核当前进程'));
    const t = el('table');
    const hr = el('tr');
    ['CPU', 'pid', '进程', 'push_off 深度', '中断使能'].forEach((h) => hr.appendChild(el('th', null, h)));
    t.appendChild(hr);
    for (const c of st.cpus) {
      const tr = el('tr');
      tr.appendChild(el('td', null, String(c.cpu)));
      tr.appendChild(el('td', null, c.pid === null ? '（调度器）' : String(c.pid)));
      tr.appendChild(el('td', null, run.dict.names[c.name] || '—'));
      tr.appendChild(el('td', 'mono', num(c.noff)));
      tr.appendChild(el('td', 'mono', num(c.intena)));
      t.appendChild(tr);
    }
    p.appendChild(t);
  }

  const sleepers = st.procs.filter((x) => x.state_name === 'SLEEPING');
  if (sleepers.length) {
    p.appendChild(el('h3', null, '等待与同步关系'));
    const byChan = {};
    for (const s of sleepers) (byChan[s.chan] = byChan[s.chan] || []).push(s);
    const t2 = el('table');
    const h2 = el('tr');
    ['等待通道 (chan)', '睡在上面的进程', '最近一次对该通道的 wakeup'].forEach((h) => h2.appendChild(el('th', null, h)));
    t2.appendChild(h2);
    for (const [chan, list] of Object.entries(byChan)) {
      const tr = el('tr');
      tr.appendChild(el('td', 'mono', hex(Number(chan))));
      tr.appendChild(el('td', null, list.map((x) => `${run.dict.names[x.name]}(${x.pid})`).join('、')));
      let found = '—';
      const upto = eventIndexAt(run, NF.cur);
      for (let i = upto; i >= 0 && i > upto - 20000; i--) {
        const e = evGet(run, i);
        if (e.kind === 'sync.wakeup' && e.detail && String(e.detail.chan) === String(chan)) {
          found = `指令 ${fmtInsn(e.insn)}`; break;
        }
      }
      tr.appendChild(el('td', 'mono', found));
      t2.appendChild(tr);
    }
    p.appendChild(t2);
  }
}

function renderVm() {
  const run = NF.runs[0];
  const p = $('#panel-vm');
  p.innerHTML = '';
  const st = stateAt(run, NF.cur);
  if (!st) { p.appendChild(el('div', 'hint', '该时刻没有快照。')); return; }

  const sel = el('select');
  sel.appendChild(new Option('（选择进程）', ''));
  for (const pr of st.procs) {
    sel.appendChild(new Option(`${run.dict.names[pr.name]} (pid ${pr.pid})`, String(pr.pid)));
  }
  sel.value = NF.selPid ? String(NF.selPid) : '';
  sel.onchange = () => { NF.selPid = sel.value ? Number(sel.value) : null; renderVm(); };
  const f = el('div', 'filters'); f.appendChild(el('span', null, '进程 ')); f.appendChild(sel);
  p.appendChild(f);

  const pr = st.procs.find((x) => x.pid === NF.selPid);
  if (!pr) { p.appendChild(el('div', 'hint', '选一个进程来查看它的用户地址空间与页表。')); return; }

  if (pr.vm_error) {
    p.appendChild(el('div', 'err-box', '页表遍历不完整 · ' + shortText(pr.vm_error, 110)));
  }
  p.appendChild(el('div', 'hint',
    `根 ${hex(pr.pagetable)} · ${num(pr.sz)} B · 用户页 ${num(pr.user_pages)} · COW ${num(pr.cow_pages)} · 页表 ${num(pr.pt_pages)}`));

  const t = el('table');
  const hr = el('tr');
  ['虚拟地址', '物理地址', '物理页号', '权限', '说明'].forEach((h) => hr.appendChild(el('th', null, h)));
  t.appendChild(hr);
  const perms = (fl) => {
    let s = '';
    s += (fl & 2) ? 'R' : '-'; s += (fl & 4) ? 'W' : '-';
    s += (fl & 8) ? 'X' : '-'; s += (fl & 16) ? 'U' : '-';
    s += (fl & 256) ? ' COW' : '';
    return s;
  };
  const ramBase = run.meta.ram_base ?? 0x80000000;
  const pageSize = run.meta.page_size ?? 4096;
  for (const [va, pa, fl] of pr.vm) {
    const tr = el('tr', 'clickable');
    tr.appendChild(el('td', 'mono', hex(va)));
    tr.appendChild(el('td', 'mono', hex(pa)));
    const idx = Math.floor((pa - ramBase) / pageSize);
    tr.appendChild(el('td', 'mono', idx >= 0 && idx < st.total ? String(idx) : '—'));
    tr.appendChild(el('td', 'mono', perms(fl)));
    let note = '';
    if (fl & 256) note = '写时复制';
    else if (!(fl & 16)) note = '内核映射';
    tr.appendChild(el('td', null, note));
    tr.onclick = () => {
      if (idx >= 0 && idx < st.total) {
        NF.selPage = idx; showPageDetail(run, st, idx);
      }
    };
    t.appendChild(tr);
  }
  p.appendChild(t);
}

function renderFs() {
  const run = NF.runs[0];
  const p = $('#panel-fs');
  p.innerHTML = '';
  const events = el('button', 'secondary-control', '文件与 I/O 事件'); events.type = 'button';
  events.onclick = () => { NF.filters.group = '文件与 I/O'; NF.filters.kind = ''; setTab('events'); };
  p.appendChild(events);
  const st = stateAt(run, NF.cur);
  if (!st) { p.appendChild(el('div', 'hint', '该时刻没有快照。')); return; }

  const section = (title, res, cols, rowfn, emptyText) => {
    p.appendChild(el('h3', null, title));
    if (!res.ok) {
      p.appendChild(el('div', 'err-box', '资源不可用 · ' + shortText(res.reason, 110)));
      return;
    }
    if (!res.rows.length) { p.appendChild(el('div', 'hint', shortText(emptyText))); return; }
    const t = el('table'); const hr = el('tr');
    cols.forEach((c) => hr.appendChild(el('th', null, c)));
    t.appendChild(hr);
    for (const r of res.rows) {
      const tr = el('tr');
      for (const v of rowfn(r)) tr.appendChild(el('td', 'mono', v));
      t.appendChild(tr);
    }
    p.appendChild(t);
  };

  const cell = (v, c) => {
    if (v === null || v === undefined) return '—';   // 没读到，不是 0
    switch (c.format) {
      case 'bool': return v ? '是' : '否';
      case 'hex':  return hex(v);
      case 'num':  return num(v);
      default:     return String(v);
    }
  };

  const resources = st.resources || [];
  if (!resources.length) {
    p.appendChild(el('div', 'hint',
                     shortText(st.resources_reason || '该内核没有可显示的资源表。')));
  }
  for (const res of resources) {
    const keys = res.show_when_any || [];
    const rows = keys.length
      ? (res.rows || []).filter((r) => keys.some((k) => r[k]))
      : (res.rows || []);
    section(res.label || res.name, { ok: res.ok, reason: res.reason, rows },
            (res.columns || []).map((c) => c.label),
            (r) => (res.columns || []).map((c) => cell(r[c.key], c)),
            res.empty || '当前没有内容。');
    for (const n of res.notes || []) {
      p.appendChild(el('div', 'hint', shortText(n)));
    }
  }

  const anyFds = st.procs.some((pr) => pr.fds);
  p.appendChild(el('h3', null, '每进程文件描述符'));
  if (!anyFds) {
    p.appendChild(el('div', 'hint', '未记录每进程 fd 表。'));
  } else {
    const t = el('table'); const hr = el('tr');
    ['进程', 'pid', '已打开的 fd'].forEach((h) => hr.appendChild(el('th', null, h)));
    t.appendChild(hr);
    for (const pr of st.procs) {
      const tr = el('tr', 'clickable');
      tr.tabIndex = 0;
      tr.onclick = () => showProcDetail(run, st, pr);
      tr.onkeydown = event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); tr.click(); } };
      tr.appendChild(el('td', null, run.dict.names[pr.name]));
      tr.appendChild(el('td', null, plain(pr.pid)));
      tr.appendChild(el('td', 'mono',
        !pr.fds ? '—' : (pr.fds.length ? pr.fds.join(', ') : '（无）')));
      t.appendChild(tr);
    }
    p.appendChild(t);
  }
}


let evFiltered = [];

function applyFilters() {
  const run = NF.runs[0];
  const f = NF.filters;
  const n = run.events.insn.length;
  evFiltered = [];
  const facetCounts = new Map();
  const txt = f.text.trim().toLowerCase();
  const from = f.from === '' ? null : Number(f.from);
  const to = f.to === '' ? null : Number(f.to);
  for (let i = 0; i < n; i++) {
    const insn = Number(run.events.insn[i]);
    if (from !== null && Number.isFinite(from) && insn < from) continue;
    if (to !== null && Number.isFinite(to) && insn > to) continue;
    const kind = run.dict.kinds[run.events.kind[i]];
    if (f.group && eventGroup(kind) !== f.group) continue;
    if (f.res && run.dict.res[run.events.res[i]] !== f.res) continue;
    if (f.pid !== '' && String(run.events.pid[i]) !== f.pid) continue;
    if (f.cpu !== '' && String(run.events.cpu[i]) !== f.cpu) continue;
    if (txt) {
      const fn = run.dict.funcs[run.events.func[i]] || '';
      const entryName = run.dict.funcs[run.events.entry_name?.[i]] || '';
      const caller = run.dict.funcs[run.events.caller?.[i]] || '';
      const d = run.events.detail[i];
      const hay = (kind + ' ' + (run.dict.res[run.events.res[i]] || '') + ' ' +
                   fn + ' ' + entryName + ' ' + caller + ' ' +
                   [run.events.func[i], run.events.entry_name?.[i], run.events.caller?.[i]]
                     .map(id => `${run.dict.full_funcs?.[id] || ''} ${run.dict.raw_funcs?.[id] || ''}`).join(' ') + ' ' +
                   (d ? JSON.stringify(d) : '')).toLowerCase();
      if (hay.indexOf(txt) < 0) continue;
    }
    const facetKind = kind.startsWith('func.') ? '@functions' : kind;
    facetCounts.set(facetKind, (facetCounts.get(facetKind) || 0) + 1);
    if (f.kind && facetKind !== f.kind) continue;
    evFiltered.push(i);
  }
  return facetCounts;
}

function renderEvents() {
  const run = NF.runs[0];
  const p = $('#panel-events');
  p.innerHTML = '';

  const heading = el('div', 'section-heading');
  const title = el('div');
  title.appendChild(el('h2', null, '事件浏览器'));
  heading.appendChild(title);
  const shortcut = el('span', 'shortcut-hint', '按 / 查找');
  heading.appendChild(shortcut);
  p.appendChild(heading);

  const f = el('div', 'filters event-filters');
  const updateTextFilter = (key, input) => {
    const start = input.selectionStart, end = input.selectionEnd;
    NF.filters[key] = input.value;
    clearTimeout(NF.filterTimer);
    NF.filterTimer = setTimeout(() => {
      renderEvents();
      const replacement = document.getElementById(input.id);
      if (replacement) {
        replacement.focus();
        if (start !== null && end !== null) replacement.setSelectionRange(start, end);
      }
    }, 180);
  };
  const selection = run.meta.event_selection || {};
  const sampled = !!selection.applied && selection.dropped > 0;
  const kinds = [...new Set(run.dict.kinds.filter((k) => !k.startsWith('func.')))].sort();
  const kSel = el('select');
  kSel.appendChild(new Option('全部事件类型', ''));
  if (run.dict.kinds.some((k) => k.startsWith('func.')))
    kSel.appendChild(new Option('函数入口', '@functions'));
  for (const k of kinds) {
    const kept = (selection.retained_kinds || {})[k] || 0;
    const raw = kept + ((selection.dropped_kinds || {})[k] || 0);
    kSel.appendChild(new Option(sampled ? `${k} · ${num(kept)} / ${num(raw)}` : k, k));
  }
  kSel.value = NF.filters.kind.startsWith('func.') ? '@functions' : NF.filters.kind;
  kSel.onchange = () => { NF.filters.kind = kSel.value; renderEvents(); };

  const rSel = el('select');
  rSel.appendChild(new Option('全部资源', ''));
  for (const r of [...new Set(run.dict.res)].sort()) rSel.appendChild(new Option(r, r));
  rSel.value = NF.filters.res;
  rSel.onchange = () => { NF.filters.res = rSel.value; renderEvents(); };

  const groupSel = el('select');
  groupSel.appendChild(new Option('全部语义分组', ''));
  const groups = [...new Set(run.dict.kinds.map(eventGroup))].sort();
  for (const group of groups) groupSel.appendChild(new Option(group, group));
  groupSel.value = NF.filters.group;
  groupSel.onchange = () => { NF.filters.group = groupSel.value; renderEvents(); };

  const pIn = el('input'); pIn.id = 'event-pid'; pIn.type = 'text'; pIn.placeholder = '例如 2';
  pIn.value = NF.filters.pid;
  pIn.oninput = () => updateTextFilter('pid', pIn);

  const pidWrap = el('label', 'filter-control');
  pidWrap.appendChild(el('span', 'filter-label', 'PID'));
  pidWrap.appendChild(pIn);
  const cpuWrap = el('label', 'filter-control');
  cpuWrap.appendChild(el('span', 'filter-label', 'CPU'));
  const cpuSel = el('select');
  cpuSel.appendChild(new Option('全部 CPU', ''));
  for (const cpu of [...new Set(run.events.cpu)].sort((a, b) => a - b)) cpuSel.appendChild(new Option(`CPU ${cpu}`, String(cpu)));
  cpuSel.value = NF.filters.cpu;
  cpuSel.onchange = () => { NF.filters.cpu = cpuSel.value; renderEvents(); };
  cpuWrap.appendChild(cpuSel);

  const kindWrap = el('label', 'filter-control');
  kindWrap.appendChild(el('span', 'filter-label', '事件类型'));
  kindWrap.appendChild(kSel);
  const resWrap = el('label', 'filter-control');
  resWrap.appendChild(el('span', 'filter-label', '资源'));
  resWrap.appendChild(rSel);

  const fromWrap = el('label', 'filter-control range-control');
  fromWrap.appendChild(el('span', 'filter-label', '指令起点'));
  const fromIn = el('input'); fromIn.id = 'event-from'; fromIn.type = 'text'; fromIn.inputMode = 'numeric'; fromIn.placeholder = '0';
  fromIn.value = NF.filters.from; fromIn.oninput = () => updateTextFilter('from', fromIn);
  fromWrap.appendChild(fromIn);
  const toWrap = el('label', 'filter-control range-control');
  toWrap.appendChild(el('span', 'filter-label', '指令终点'));
  const toIn = el('input'); toIn.id = 'event-to'; toIn.type = 'text'; toIn.inputMode = 'numeric'; toIn.placeholder = num(run.meta.total_insns);
  toIn.value = NF.filters.to; toIn.oninput = () => updateTextFilter('to', toIn);
  toWrap.appendChild(toIn);

  const jump = el('button', 'secondary-control', '跳到当前时刻');
  jump.onclick = () => { scrollToCurrent(); };
  const clear = el('button', 'ghost-control', '清除筛选');
  clear.onclick = () => {
    clearTimeout(NF.filterTimer);
    NF.filters = { text: '', kind: '', res: '', pid: '', cpu: '', group: '', from: '', to: '' };
    $('#quick-query').value = '';
    renderEvents();
  };

  const groupWrap = el('label', 'filter-control');
  groupWrap.appendChild(el('span', 'filter-label', '语义分组'));
  groupWrap.appendChild(groupSel);
  f.appendChild(kindWrap); f.appendChild(resWrap); f.appendChild(jump); f.appendChild(clear);
  p.appendChild(f);

  const advanced = el('details', 'advanced-filters');
  advanced.open = NF.advancedFiltersOpen || !!(NF.filters.group || NF.filters.pid || NF.filters.cpu || NF.filters.from || NF.filters.to);
  advanced.ontoggle = () => { NF.advancedFiltersOpen = advanced.open; };
  advanced.appendChild(el('summary', null, '更多筛选'));
  const advancedFields = el('div', 'filters advanced-filter-fields');
  advancedFields.appendChild(groupWrap); advancedFields.appendChild(pidWrap); advancedFields.appendChild(cpuWrap);
  advancedFields.appendChild(fromWrap); advancedFields.appendChild(toWrap);
  advanced.appendChild(advancedFields);

  const presets = el('div', 'range-presets');
  presets.appendChild(el('span', null, '时间范围'));
  const preset = (label, from, to) => {
    const b = el('button', 'range-preset' + (NF.filters.from === from && NF.filters.to === to ? ' selected' : ''), label);
    b.type = 'button';
    b.onclick = () => { NF.filters.from = from; NF.filters.to = to; renderEvents(); };
    presets.appendChild(b);
  };
  preset('全部', '', '');
  const si = stateIndexAt(run, NF.cur);
  if (si >= 0) preset('当前快照', String(si ? run.states[si - 1].insn : 0), String(run.states[si].insn));
  if (run.meta.program_start_insn) preset('目标程序', String(run.meta.program_start_insn), '');
  advanced.appendChild(presets);
  p.appendChild(advanced);

  const facetCounts = applyFilters();
  const info = el('div', 'result-bar');
  info.appendChild(el('strong', null, `${num(evFiltered.length)} 条结果`));
  info.appendChild(el('span', null, sampled
    ? ` / ${num(run.events.insn.length)} 条浏览样本 · 原始 ${num(selection.raw)} 条`
    : ` / ${num(run.events.insn.length)} 条事件`));
  const resultNav = el('div', 'result-nav');
  const position = el('span', 'result-position');
  const previous = el('button', 'secondary-control', '上一条'); previous.type = 'button';
  const next = el('button', 'secondary-control', '下一条'); next.type = 'button';
  previous.title = '上一条匹配事件 (K)'; next.title = '下一条匹配事件 (J)';
  previous.onclick = () => navigateResults(-1);
  next.onclick = () => navigateResults(1);
  resultNav.appendChild(position); resultNav.appendChild(previous); resultNav.appendChild(next);
  info.appendChild(resultNav);
  p.appendChild(info);
  updateResultNavigation();
  if (!evFiltered.length) {
    const empty = el('div', 'event-empty');
    empty.appendChild(el('strong', null, sampled ? '样本中没有匹配事件' : '没有匹配的事件'));
    empty.appendChild(el('p', null, '清除筛选或调整范围。'));
    p.appendChild(empty);
    return;
  }

  const facet = el('div', 'event-facets');
  const facetRows = [...facetCounts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 8);
  if (NF.filters.kind && facetCounts.has(NF.filters.kind) &&
      !facetRows.some(([kind]) => kind === NF.filters.kind)) {
    facetRows.unshift([NF.filters.kind, facetCounts.get(NF.filters.kind)]);
  }
  facetRows.forEach(([kind, count]) => {
    const b = el('button', 'facet' + (NF.filters.kind === kind ? ' selected' : ''));
    b.type = 'button'; b.title = `筛选 ${kind === '@functions' ? '函数入口' : kind}`;
    b.appendChild(el('span', null, kind === '@functions' ? '函数入口' : kind)); b.appendChild(el('b', null, num(count)));
    b.onclick = () => { NF.filters.kind = NF.filters.kind === kind ? '' : kind; renderEvents(); };
    facet.appendChild(b);
  });
  if (facet.childElementCount) p.appendChild(facet);

  const density = el('details', 'event-density');
  const bars = el('div', 'density-bars');
  const bins = 48; const totalInsn = Number(run.meta.total_insns) || 1; const binCounts = Array(bins).fill(0);
  for (const i of evFiltered) {
    const at = Math.min(bins - 1, Math.floor(Number(run.events.insn[i]) / totalInsn * bins));
    binCounts[at]++;
  }
  const peak = Math.max(1, ...binCounts);
  density.appendChild(el('summary', null,
    `${sampled ? '样本' : '匹配事件'}时间分布 · 每段 ${axisNum(totalInsn / bins)} 指令`));
  binCounts.forEach((count, bin) => {
    const b = el('button', 'density-bar'); b.type = 'button'; b.title = `${num(count)} 条事件`;
    b.setAttribute('aria-label', `第 ${bin + 1} 个时间段，${num(count)} 条事件`);
    b.style.height = `${Math.max(4, Math.round(count / peak * 100))}%`;
    b.onclick = () => { NF.filters.from = String(Math.floor(bin / bins * totalInsn)); NF.filters.to = String(Math.ceil((bin + 1) / bins * totalInsn)); renderEvents(); };
    bars.appendChild(b);
  });
  density.appendChild(bars);
  const densityAxis = el('div', 'density-axis');
  densityAxis.appendChild(el('span', null, '0'));
  densityAxis.appendChild(el('span', null, axisNum(totalInsn / 2)));
  densityAxis.appendChild(el('span', null, axisNum(totalInsn)));
  density.appendChild(densityAxis); p.appendChild(density);

  const scroll = el('div'); scroll.id = 'evscroll';
  const table = el('table'); table.className = 'event-table';
  const hr = el('tr');
  ['指令号', 'tick', 'CPU', 'PID', '事件', '资源', '函数', '要点'].forEach((h) => hr.appendChild(el('th', null, h)));
  table.appendChild(hr);
  const body = el('tbody'); table.appendChild(body);
  scroll.appendChild(table);
  p.appendChild(scroll);

  const ROW = 34;
  const span = window.matchMedia('(max-width: 560px)').matches ? 3 : 8;
  const spacerTop = el('tr'); const tdT = el('td'); tdT.colSpan = span; spacerTop.appendChild(tdT);
  const spacerBot = el('tr'); const tdB = el('td'); tdB.colSpan = span; spacerBot.appendChild(tdB);

  function paint() {
    const top = scroll.scrollTop;
    const h = scroll.clientHeight;
    const first = Math.max(0, Math.floor(top / ROW) - 10);
    const last = Math.min(evFiltered.length, Math.ceil((top + h) / ROW) + 10);
    body.innerHTML = '';
    tdT.style.height = (first * ROW) + 'px';
    tdB.style.height = ((evFiltered.length - last) * ROW) + 'px';
    body.appendChild(spacerTop);
    for (let k = first; k < last; k++) {
      const i = evFiltered[k];
      const e = evGet(run, i);
      const tr = el('tr', 'clickable');
      tr.tabIndex = 0;
      tr.setAttribute('aria-label', `${eventLabel(e)}，指令 ${fmtInsn(e.insn)}，${summarize(e)}`);
      if (NF.selEvent === i) tr.className += ' sel';
      tr.appendChild(el('td', 'mono', fmtInsn(e.insn)));
      tr.appendChild(el('td', 'mono', e.tick === null ? '—' : String(e.tick)));
      tr.appendChild(el('td', 'mono', String(e.cpu)));
      tr.appendChild(el('td', 'mono', e.pid === null ? '—' : String(e.pid)));
      const kindCell = el('td');
      kindCell.appendChild(el('span', 'event-kind', eventLabel(e)));
      const brief = e.entry ? (e.entryName || e.func) : summarize(e);
      if (brief) kindCell.appendChild(el('span', 'event-brief', ' · ' + brief));
      tr.appendChild(kindCell);
      tr.appendChild(el('td', null, e.res));
      tr.appendChild(el('td', 'mono', e.func || '—'));
      tr.appendChild(el('td', 'mono', summarize(e)));
      tr.onclick = () => { selectEvent(i); };
      tr.onkeydown = (key) => {
        if (key.key === 'Enter' || key.key === ' ') { key.preventDefault(); selectEvent(i); }
      };
      body.appendChild(tr);
    }
    body.appendChild(spacerBot);
  }
  scroll.onscroll = paint;
  paint();
  scroll._paint = paint;
  scroll._rowh = ROW;
}

function summarize(e) {
  const d = e.detail || {};
  switch (e.kind) {
    case 'syscall.enter':
      return d.syscall || d.syscall_num !== undefined
        ? `${d.syscall || d.syscall_num}(${(d.args || []).slice(0, 3).map(hex).join(', ')})` : '';
    case 'trap.page_fault':
      return d.fault_kind || d.fault_va !== undefined
        ? `${d.fault_kind || '缺页'} @ ${hex(d.fault_va)}` : '';
    case 'trap.exception': return d.cause_name || '';
    case 'interrupt.timer': case 'interrupt.external': return d.cause_name || '';
    // Task identity comes from analysis; an unresolved endpoint stays unknown.
    case 'sched.switch': {
      const side = (n) => n == null || n === '' ? '?' : String(n);
      return `${side(d.from_proc)} → ${side(d.to_proc)}`;
    }
    case 'phys.free': return hex(d.pa);
    case 'phys.alloc':
      if (d.allocated_pa === 0) return '分配失败（物理内存耗尽）';
      if (d.allocated_pa) return '分配一页 ' + hex(d.allocated_pa);
      return '分配一页（返回值外部不可见）';
    case 'pagetable.map': return `va=${hex(d.va)} pa=${hex(d.pa)} 大小=${num(d.size)} 权限=${hex(d.perm)}`;
    case 'pagetable.unmap': return `va=${hex(d.va)} ${num(d.npages)} 页`;
    case 'vm.copy': return `父页表=${hex(d.old)} 子页表=${hex(d.new)} 大小=${num(d.sz)}`;
    case 'bcache.read': case 'bcache.get':
      return d.dev !== undefined && d.blockno !== undefined ? `dev=${d.dev} block=${d.blockno}` : '';
    case 'bcache.result':
      return [d.outcome, d.first_block !== undefined ? `block=${d.first_block}` : '',
        d.blocks !== undefined ? `${num(d.blocks)} 块` : ''].filter(Boolean).join(' · ');
    case 'disk.io': return d.write ? '写盘' : '读盘';
    case 'sync.sleep': case 'sync.wakeup': return d.chan !== undefined ? `chan=${hex(d.chan)}` : '';
    case 'kernel.panic': return d.msg || 'panic';
    case 'inode.get':
      return d.dev !== undefined && d.inum !== undefined ? `dev=${d.dev} inum=${d.inum}` : '';
    default: {
      const ks = Object.keys(d);
      if (!ks.length) return '';
      return ks.slice(0, 3).map((k) => `${k}=${typeof d[k] === 'number' ? hex(d[k]) : d[k]}`).join(' ');
    }
  }
}

function scrollToCurrent() {
  const scroll = $('#evscroll');
  if (!scroll) return;
  let k = 0;
  for (; k < evFiltered.length; k++) {
    if (NF.runs[0].events.insn[evFiltered[k]] >= NF.cur) break;
  }
  scroll.scrollTop = Math.max(0, k * scroll._rowh - scroll.clientHeight / 2);
  scroll._paint();
}

function updateResultNavigation() {
  const bar = $('#panel-events .result-nav');
  if (!bar) return;
  const position = evFiltered.indexOf(NF.selEvent);
  const previous = bar.querySelectorAll('button')[0];
  const next = bar.querySelectorAll('button')[1];
  bar.querySelector('.result-position').textContent = position >= 0
    ? `${num(position + 1)} / ${num(evFiltered.length)}`
    : (NF.selEvent === null ? `0 / ${num(evFiltered.length)}` : '选中项不在结果中');
  previous.disabled = !evFiltered.length || position === 0;
  next.disabled = !evFiltered.length || position === evFiltered.length - 1;
}

function navigateResults(direction) {
  if (!evFiltered.length) return;
  const current = evFiltered.indexOf(NF.selEvent);
  const position = current < 0 ? (direction > 0 ? 0 : evFiltered.length - 1)
    : Math.max(0, Math.min(evFiltered.length - 1, current + direction));
  selectEvent(evFiltered[position]);
  const scroll = $('#evscroll');
  if (scroll) {
    scroll.scrollTop = Math.max(0, position * scroll._rowh - scroll.clientHeight / 2);
    scroll._paint();
  }
}

function selectEvent(i) {
  if (!document.body.classList.contains('detail-modal')) NF.pendingDetailTrigger = document.activeElement;
  const debugNav = document.activeElement?.dataset?.debugNav;
  NF.selEvent = i;
  NF.functionFocusIndex = i;
  NF.cur = NF.runs[0].events.insn[i];
  if (NF.tab === 'events') {
    renderTime();
    renderDelta();
    $('#evscroll')?._paint();
    updateResultNavigation();
  } else render();
  if (NF.tab !== 'functions') showEventDetail(NF.runs[0], i);
  else if (window.matchMedia('(max-width: 850px)').matches) {
    NF.detailView = 'source'; showEventDetail(NF.runs[0], i);
  } else requestAnimationFrame(() => {
    const target = debugNav ? $(`.debug-toolbar button[data-debug-nav="${debugNav}"]:not(:disabled)`)
      : $('.sequence-node[aria-current="true"]');
    target?.focus({preventScroll: true});
  });
}

function renderFunctions() {
  const run = NF.runs[0];
  const p = $('#panel-functions');
  p.innerHTML = '';
  const heading = el('div', 'section-heading');
  const title = el('div');
  title.appendChild(el('h2', null, '函数轨迹'));
  const entryCounts = run.meta.function_entries;
  const scope = entryCounts && entryCounts.raw > entryCounts.retained
    ? `${num(entryCounts.retained)} / ${num(entryCounts.raw)}`
    : num(entryCounts?.retained ?? 0);
  const returns = run.meta.function_returns || { raw: 0, matched: 0, nested_entries: 0 };
  title.appendChild(el('div', 'section-subtitle', `入口事件 ${scope} 条`));
  heading.appendChild(title);
  p.appendChild(heading);

  const entries = [];
  for (let i = 0; i < run.events.insn.length; i++) {
    const kind = run.dict.kinds[run.events.kind[i]];
    if (run.events.entry ? run.events.entry[i] !== 1 : !kind.startsWith('func.')) continue;
    const entryName = run.events.entry_name?.[i] ?? -1;
    const callerId = run.events.caller?.[i] ?? -1;
    const fn = (entryName >= 0 ? run.dict.funcs[entryName] : '')
      || run.dict.funcs[run.events.func[i]] || kind.slice(5);
    const caller = callerId >= 0 ? run.dict.funcs[callerId] : '';
    const path = run.events.stack?.[i]?.map((id) => run.dict.funcs[id]) || null;
    const fnId = entryName >= 0 ? entryName : run.events.func[i];
    entries.push({ i, fn: functionName(run, fnId, true) || fn, fnId, callerId,
      caller: functionName(run, callerId, true) || caller, path,
      insn: run.events.insn[i], cpu: run.events.cpu[i], pid: run.events.pid[i] });
  }
  if (!entries.length) {
    if (NF.selEvent != null) {
      const debuggerPane = el('div', 'debugger standalone-debugger');
      p.appendChild(debuggerPane); renderDebugger(run, NF.selEvent, debuggerPane);
      return;
    }
    const empty = el('div', 'event-empty');
    empty.appendChild(el('strong', null, '没有函数入口事件'));
    const viewEvents = el('button', 'secondary-control', '查看其他事件');
    viewEvents.type = 'button';
    viewEvents.onclick = () => setTab('events');
    empty.appendChild(viewEvents);
    p.appendChild(empty);
    return;
  }

  const controls = el('div', 'trace-controls');
  const search = el('input'); search.type = 'search'; search.placeholder = '筛选函数名'; search.id = 'function-search'; search.setAttribute('aria-label', '筛选函数名');
  const cpu = el('select'); cpu.id = 'function-cpu'; cpu.setAttribute('aria-label', '筛选 CPU'); cpu.appendChild(new Option('全部 CPU', ''));
  for (const c of [...new Set(entries.map((e) => e.cpu))].sort((a, b) => a - b)) cpu.appendChild(new Option(`CPU ${c}`, String(c)));
  const limit = el('select'); limit.id = 'function-limit'; limit.setAttribute('aria-label', '显示条数');
  for (const n of [40, 80, 160]) limit.appendChild(new Option(`最近 ${n} 条`, String(n)));
  limit.value = '80';
  const grouping = el('select'); grouping.id = 'function-grouping'; grouping.setAttribute('aria-label', '函数轨迹视图');
  grouping.appendChild(new Option('调用关系', 'caller'));
  grouping.appendChild(new Option('名称层级', 'namespace'));
  if (returns.nested_entries) grouping.appendChild(new Option('调用栈', 'stack'));
  if (returns.nested_entries) grouping.value = 'stack';
  else if (!entries.some((e) => e.caller)) grouping.value = 'namespace';
  search.value = NF.functionFilters.text;
  cpu.value = NF.functionFilters.cpu;
  limit.value = NF.functionFilters.limit;
  if ([...grouping.options].some(option => option.value === NF.functionFilters.grouping)) grouping.value = NF.functionFilters.grouping;
  controls.appendChild(search); controls.appendChild(cpu); controls.appendChild(grouping);
  controls.appendChild(limit); p.appendChild(controls);

  const grid = el('div', 'trace-grid');
  const treePanel = el('section', 'trace-panel');
  const treeTitle = el('div', 'trace-panel-title', '调用关系');
  const treeNote = el('div', 'trace-panel-note', '由返回地址关联');
  treePanel.appendChild(treeTitle);
  treePanel.appendChild(treeNote);
  const sequencePanel = el('section', 'trace-panel');
  sequencePanel.appendChild(el('div', 'trace-panel-title', '入口顺序'));
  const tree = el('div', 'function-tree'); const sequence = el('div', 'function-sequence');
  treePanel.appendChild(tree); sequencePanel.appendChild(sequence);
  grid.appendChild(treePanel); grid.appendChild(sequencePanel);
  const workspace = el('div', 'debug-workspace');
  const debuggerPane = el('div', 'debugger');
  workspace.append(grid, debuggerPane); p.appendChild(workspace);

  function paint() {
    NF.functionFilters = {text: search.value, cpu: cpu.value, limit: limit.value, grouping: grouping.value};
    const q = search.value.trim().toLowerCase();
    const selectedCpu = cpu.value;
    const filtered = entries.filter((e) => (!q || e.fn.toLowerCase().includes(q) || e.caller.toLowerCase().includes(q) || run.dict.raw_funcs?.[e.fnId]?.toLowerCase().includes(q) || (e.path || []).some((name) => name.toLowerCase().includes(q))) && (selectedCpu === '' || String(e.cpu) === selectedCpu));
    const counts = new Map();
    for (const e of filtered) counts.set(e.fnId, (counts.get(e.fnId) || 0) + 1);
    tree.innerHTML = '';
    if (grouping.value === 'stack') {
      treeTitle.textContent = '调用栈';
      treeNote.textContent = '已匹配的入口与返回事件';
      const chains = new Map();
      for (const e of filtered) {
        if (!e.path || e.path.length < 2) continue;
        const key = (run.events.stack?.[e.i] || e.path).join('\0');
        if (!chains.has(key)) chains.set(key, { path: e.path, count: 0, index: e.i });
        chains.get(key).count++;
      }
      [...chains.values()].sort((a, b) => b.count - a.count || a.path.join().localeCompare(b.path.join()))
        .slice(0, 120).forEach((chain) => {
          const row = el('button', 'function-row stack-chain'); row.type = 'button';
          row.style.setProperty('--bar', `${Math.round(chain.count / Math.max(1, filtered.length) * 100)}%`);
          row.title = chain.path.join(' → ');
          row.appendChild(el('span', 'function-name', chain.path.join(' → ')));
          row.appendChild(el('span', 'function-count', num(chain.count)));
          row.onclick = () => selectEvent(chain.index);
          tree.appendChild(row);
        });
      if (!chains.size) tree.appendChild(el('div', 'trace-muted', '当前筛选中没有可匹配的嵌套帧。'));
    } else if (grouping.value === 'caller') {
      treeTitle.textContent = '调用关系';
      treeNote.textContent = '由返回地址关联';
      const edges = new Map();
      for (const e of filtered) {
        if (!e.caller) continue;
        const key = `${e.callerId}\0${e.fnId}`;
        if (!edges.has(key)) edges.set(key, { caller: e.caller, fn: e.fn, count: 0, index: e.i });
        edges.get(key).count++;
      }
      [...edges.values()].sort((a, b) => b.count - a.count || a.fn.localeCompare(b.fn))
        .slice(0, 120).forEach((edge) => {
          const row = el('button', 'function-row'); row.type = 'button';
          row.style.setProperty('--bar', `${Math.round(edge.count / Math.max(1, filtered.length) * 100)}%`);
          row.title = '定位到一条入口事件';
          row.appendChild(el('span', 'function-name', `${edge.caller} → ${edge.fn}`));
          row.appendChild(el('span', 'function-count', num(edge.count)));
          row.onclick = () => selectEvent(edge.index);
          tree.appendChild(row);
        });
      if (!edges.size) tree.appendChild(el('div', 'trace-muted', '这些入口的返回地址无法定位调用方。'));
    } else {
      treeTitle.textContent = '名称层级';
      treeNote.textContent = '按命名空间汇总入口次数';
      const root = { label: '', count: 0, children: new Map(), fn: null };
      const partsOf = functionParts;
      for (const [fnId, count] of counts) {
        const fn = functionName(run, fnId, true);
        let node = root; node.count += count;
        for (const part of partsOf(fn)) {
          if (!node.children.has(part)) node.children.set(part, { label: part, count: 0, children: new Map(), fn: null });
          node = node.children.get(part); node.count += count;
        }
        node.fn = fn;
      }
      const paintNode = (node, depth, parent) => {
        [...node.children.values()].sort((a, b) => b.count - a.count || a.label.localeCompare(b.label)).forEach((child) => {
          const row = el('button', 'function-row'); row.type = 'button';
          row.style.paddingLeft = `${8 + depth * 16}px`;
          row.style.setProperty('--bar', `${Math.round(child.count / Math.max(1, root.count) * 100)}%`);
          row.title = child.fn ? `在事件浏览器中筛选 ${child.fn}` : `展开 ${child.label}`;
          const marker = child.children.size ? '› ' : '  ';
          row.appendChild(el('span', 'function-name', marker + child.label));
          row.appendChild(el('span', 'function-count', num(child.count)));
          parent.appendChild(row);
          if (child.children.size) {
            const children = el('div', 'function-children');
            children.hidden = depth > 0;
            let painted = false;
            row.setAttribute('aria-expanded', String(!children.hidden));
            row.onclick = () => {
              children.hidden = !children.hidden;
              if (!children.hidden && !painted) { paintNode(child, depth + 1, children); painted = true; }
              row.setAttribute('aria-expanded', String(!children.hidden));
              row.firstChild.textContent = `${children.hidden ? '› ' : '⌄ '}${child.label}`;
            };
            parent.appendChild(children);
            if (!children.hidden) { paintNode(child, depth + 1, children); painted = true; }
          } else if (child.fn) {
            row.onclick = () => { NF.filters.text = child.fn; setTab('events'); };
          }
        });
      };
      paintNode(root, 0, tree);
      if (!counts.size) tree.appendChild(el('div', 'trace-muted', '没有匹配的函数。'));
    }

    sequence.innerHTML = '';
    const cap = Number(limit.value) || 80;
    const focusPos = filtered.findIndex((e) => e.i === NF.functionFocusIndex);
    const start = focusPos < 0 ? Math.max(0, filtered.length - cap)
      : Math.max(0, Math.min(focusPos - 5, filtered.length - cap));
    filtered.slice(start, start + cap).forEach((e, index) => {
      if (index) sequence.appendChild(el('div', 'sequence-link'));
      const node = el('button', 'sequence-node'); node.type = 'button'; node.title = '定位到这条入口事件';
      if (e.i === NF.functionFocusIndex) node.setAttribute('aria-current', 'true');
      node.appendChild(el('span', 'sequence-index', String(start + index + 1).padStart(2, '0')));
      const name = el('span', 'sequence-function', compactFunction(e.fn)); name.title = e.fn;
      node.appendChild(name);
      node.appendChild(el('span', 'sequence-meta', `${fmtInsn(e.insn)} · CPU ${e.cpu}${e.path?.length > 1 ? ` · ${e.path.join(' → ')}` : e.caller ? ` · ${e.caller} →` : ''}`));
      node.onclick = () => selectEvent(e.i);
      sequence.appendChild(node);
    });
    if (!filtered.length) sequence.appendChild(el('div', 'trace-muted', '没有匹配的入口事件。'));
    const found = filtered.findIndex(e => e.i === NF.functionFocusIndex);
    const focus = Math.max(0, found);
    if (found < 0 && !q && selectedCpu === '' && NF.selEvent != null && NF.functionFocusIndex === NF.selEvent)
      renderDebugger(run, NF.selEvent, debuggerPane);
    else if (filtered.length) renderDebugger(run, filtered[focus].i, debuggerPane, {
      available: delta => focus + delta >= 0 && focus + delta < filtered.length,
      go: delta => selectEvent(filtered[focus + delta].i),
    });
    else debuggerPane.replaceChildren(el('p', 'source-empty', '选择函数入口事件查看源码。'));
  }
  search.oninput = paint; cpu.onchange = paint; grouping.onchange = paint;
  limit.onchange = paint; paint();
}


function renderMetrics() {
  const run = NF.runs[0];
  const m = run.metrics;
  const p = $('#panel-metrics');
  p.innerHTML = '';

  const mk = (title, series) => {
    p.appendChild(el('h3', null, title));
    const named = series.filter((s) => s.name);
    if (named.length > 1) {
      const legend = el('div', 'chart-legend');
      named.forEach((s) => {
        const item = el('span');
        const swatch = el('i'); swatch.style.background = s.color;
        item.appendChild(swatch); item.appendChild(document.createTextNode(s.name));
        legend.appendChild(item);
      });
      p.appendChild(legend);
    }
    const cv = el('canvas', 'chart');
    p.appendChild(cv);
    setTimeout(() => drawChart(cv, series, { title }), 0);
  };

  const usedPts = run.states.map((s) => [s.insn, s.used]);
  const sharedPts = run.states.map((s) => [s.insn, s.shared]);
  const anyVal = (pts) => pts.some((p) => p[1] !== null && p[1] !== undefined);
  if (anyVal(usedPts) || anyVal(sharedPts)) {
    mk('物理内存占用（每次快照）', [
      { color: '#4aa3ff', name: '已用', points: usedPts },
      { color: '#3fb950', name: '共享', points: sharedPts },
    ]);
  } else {
    p.appendChild(el('h3', null, '物理内存占用（每次快照）'));
    p.appendChild(el('div', 'hint', '无可用快照数据。'));
  }

  const cum = (pred) => {
    const pts = []; let n = 0;
    const E = run.events;
    for (let i = 0; i < E.insn.length; i++) {
      if (pred(run.dict.kinds[E.kind[i]])) { n++; pts.push([E.insn[i], n]); }
    }
    if (!pts.length) pts.push([0, 0]);
    return pts;
  };
  // A missing metric cannot be plotted as zero.
  const mkWatched = (title, metric, series) => {
    if (m[metric] === null || m[metric] === undefined) {
      p.appendChild(el('h3', null, title));
      p.appendChild(el('div', 'hint', '无观测点'));
      return;
    }
    mk(title, series);
  };
  mk('累计系统调用', [{ color: '#a371f7', name: '系统调用', points: cum((k) => k === 'syscall.enter') }]);
  mk('累计缺页异常', [{ color: '#d29922', name: '缺页', points: cum((k) => k === 'trap.page_fault') }]);
  mkWatched('累计上下文切换', 'context_switches',
    [{ color: '#4aa3ff', name: '切换', points: cum((k) => k === 'sched.switch') }]);
  mkWatched('累计磁盘 I/O', 'disk_io',
    [{ color: '#f85149', name: '磁盘 I/O', points: cum((k) => k === 'disk.io') }]);
  mkWatched('累计 kalloc / kfree', 'kalloc', [
    { color: '#3fb950', name: 'kalloc', points: cum((k) => k === 'phys.alloc') },
    { color: '#f85149', name: 'kfree', points: cum((k) => k === 'phys.free') },
  ]);

  p.appendChild(el('h3', null, '全部事件类型统计'));
  // Distinguish observed counts, armed-but-silent probes, and absent probes.
  p.appendChild(el('div', 'hint', '0：未触发 · —：未观测'));
  const drops = (run.metrics.sampling || {}).drops;
  if (drops) {
    const kept = run.events.insn.length;
    const hit = kept + drops;
    p.appendChild(el('div', 'hint',
      `抽样：记录 ${num(kept)} / 命中 ${num(hit)} · 丢弃 ${num(drops)}（${(100 * drops / hit).toFixed(1)}%）`));
  }
  const t = el('table'); const hr = el('tr');
  ['事件类型', '次数', ''].forEach((h) => hr.appendChild(el('th', null, h)));
  t.appendChild(hr);

  const row = (k, count, cls, ...tags) => {
    const tr = el('tr', cls);
    tr.appendChild(el('td', null, k));
    tr.appendChild(el('td', 'mono', count));
    const td = el('td');
    for (const tag of tags) if (tag) td.appendChild(tag);
    tr.appendChild(td);
    t.appendChild(tr);
    return tr;
  };

  const sampled = (run.metrics.sampling || {}).kinds || {};
  const sampleTag = (k) => {
    const rates = sampled[k];
    if (!rates || !rates.length) return null;
    const hi = rates.filter((r) => r > 1);
    const mixed = rates.some((r) => r <= 1);
    const tag = el('span', 'tag why-empty',
      mixed ? `部分 1/${hi.join('、1/')} 抽样` : `1/${hi.join('、1/')} 抽样`);
    tag.title = mixed ? '该类事件的观察点采用不同采样率' : `每 ${hi[0]} 次命中记录 1 条`;
    return tag;
  };
  // The first hit is recorded; k samples at rate N bound hits to [k, kN].
  const sampleRange = (k, v) => {
    const r = sampled[k];
    if (!r || !r.length) return null;
    const hi = Math.max(...r);
    if (hi <= 1) return null;
    const s = el('span', 'dim', ` 实际 ${num(v)}～${num(v * hi)}`);
    s.title = `实际次数范围：记录数至记录数 × ${hi}`;
    return s;
  };

  const ent = Object.entries(run.metrics.by_kind).sort((a, b) => b[1] - a[1]);
  for (const [k, v] of ent) {
    const tr = row(k, num(v), 'clickable', sampleTag(k), sampleRange(k, v));
    tr.onclick = () => { NF.filters.kind = k; setTab('events'); };
  }
  for (const k of (run.metrics.armed_silent || [])) {
    const tag = el('span', 'tag why-empty', '这趟没发生');
    const tr = row(k, '0', 'clickable k-silent', tag);
    tr.onclick = () => { NF.filters.kind = k; setTab('events'); };
  }
  const absent = run.metrics.absent_declared || {};
  for (const k of Object.keys(absent).sort()) {
    const why = absent[k].why;
    const tag = el('span', 'tag why-' + why,
      why === 'feature' ? '本内核没有' : '缺少对应观察点');
    tag.title = absent[k].evidence || '';
    row(k, '—', 'k-absent', tag);
  }
  p.appendChild(t);
}

function renderConsole() {
  const run = NF.runs[0];
  const p = $('#panel-console');
  p.innerHTML = '';
  const pre = el('pre', 'console', run.meta.console || '(没有控制台输出)');
  p.appendChild(pre);
}


function showEventDetail(run, i) {
  openDetail();
  const box = $('#detail');
  box.innerHTML = '';
  const e = evGet(run, i);
  const tabs = el('div', 'detail-tabs');
  const info = el('div', 'detail-info');
  const debuggerHost = el('div', 'debugger detail-debugger');
  const pane = $('.right');
  configureDetailBack();
  const switchView = value => {
    NF.detailView = value;
    info.hidden = value !== 'details'; debuggerHost.hidden = value === 'details';
    pane.classList.toggle('source-open', value !== 'details');
    for (const button of tabs.children) button.setAttribute('aria-pressed', String(button.dataset.view === value));
    if (value !== 'details' && !debuggerHost.childElementCount) {
      const indices = NF.detailEventIndices || (NF.tab === 'events' ? evFiltered : null);
      const position = indices ? indices.indexOf(i) : i;
      const target = delta => indices ? indices[position + delta] : i + delta;
      renderDebugger(run, i, debuggerHost, {
        available: delta => position >= 0 && target(delta) != null && target(delta) >= 0 && target(delta) < run.events.insn.length,
        go: delta => { selectEvent(target(delta)); requestAnimationFrame(() => $('#detail [data-debug-nav="' + delta + '"]:not(:disabled)')?.focus({preventScroll: true})); },
      });
    }
    debuggerHost.dataset.mobileView = value === 'stack' ? 'stack' : 'source';
  };
  debuggerHost.addEventListener('source-frame-selected', () => switchView('source'));
  if (NF.detailReturn) {
    const label = `返回${NF.detailReturn.label || '资源详情'}`;
    const back = el('button', 'secondary-control detail-context-back', label); back.type = 'button';
    const restore = () => {
      const context = NF.detailReturn; NF.detailReturn = null; NF.detailEventIndices = null;
      NF.cur = context.insn; NF.selEvent = null; render();
      pane.classList.remove('source-open'); box.replaceChildren(...context.nodes);
      configureDetailBack();
      context.trigger?.focus({preventScroll: true});
    };
    back.onclick = restore;
    configureDetailBack(restore, label);
    box.appendChild(back);
  }
  for (const [value, text] of [['details', '事件详情'], ['stack', '调用栈'], ['source', '源码']]) {
    const button = el('button', 'secondary-control', text); button.type = 'button'; button.dataset.view = value;
    button.onclick = () => switchView(value); tabs.appendChild(button);
  }
  box.append(tabs, info, debuggerHost);
  const appendDetail = node => info.appendChild(node);

  appendDetail(sec('选中的事件', [
    ['事件类型', eventLabel(e)], ['资源', e.res], ['指令号', fmtInsn(e.insn)],
    ['tick', e.tick === null ? '—' : String(e.tick)], ['CPU', String(e.cpu)],
    ['进程', e.pid === null ? '—' : `pid ${e.pid}`],
    ['PC', hex(e.pc)],
    ['函数', e.func || '—'],
  ]));
  if (e.entry) {
    const trace = el('button', 'secondary-control detail-action', '查看调用关系');
    trace.type = 'button';
    trace.onclick = () => {
      NF.functionFilters.text = e.entryName || e.func || '';
      NF.functionFilters.grouping = 'caller';
      NF.functionFocusIndex = i;
      setTab('functions');
    };
    appendDetail(trace);
  }

  if (e.detail && Object.keys(e.detail).length) {
    const rows = Object.entries(e.detail).map(([k, v]) => {
      if (Array.isArray(v)) return [k, v.map(hex).join(', ')];
      if (isHexStr(v)) return [k, v];
      if (typeof v === 'number' && v > 4096) {
        return [k, Math.abs(v) > EXACT_MAX ? hex(v) : `${hex(v)} (${num(v)})`];
      }
      return [k, String(v)];
    });
    appendDetail(sec('事件参数', rows));
  }

  if (e.unknown && e.unknown.length) {
    const d = el('div', 'dsec');
    d.appendChild(el('div', 't', '未知字段'));
    const ul = el('ul');
    for (const u of e.unknown) {
      ul.appendChild(el('li', 'unknown', {
        allocated_pa: 'kalloc 返回页：未记录',
        csr: 'CSR：未记录',
      }[u] || u));
    }
    d.appendChild(ul);
    appendDetail(d);
  }

  const si = stateIndexAt(run, e.insn);
  if (si >= 0 && si + 1 < run.states.length) {
    const a = run.states[si], b = run.states[si + 1];
    const rows = [];
    const cmp = (label, va, vb) => {
      if (va === null || vb === null || va === undefined || vb === undefined) {
        rows.push([label, `${num(va)} → ${num(vb)}`]);
        return;
      }
      const d = vb - va;
      rows.push([label, `${num(va)} → ${num(vb)}  ${d === 0 ? '' : (d > 0 ? '+' : '') + num(d)}`]);
    };
    const plen = (s) => (s.procs_ok === false ? null : s.procs.length);
    cmp('已用物理页', a.used, b.used);
    cmp('空闲物理页', a.free, b.free);
    cmp('多进程共享页', a.shared, b.shared);
    cmp('活动进程数', plen(a), plen(b));
    appendDetail(sec(
      `快照 ${si} → ${si + 1}`,
      rows));
  }

  const near = [];
  for (let k = Math.max(0, i - 6); k < Math.min(run.events.insn.length, i + 7); k++) {
    near.push(k);
  }
  appendDetail(eventLinks(run, '相邻事件', near));
  switchView(NF.detailView || 'details');
}

function showPageDetail(run, st, idx) {
  resetResourceDetail();
  NF.detailResourceLabel = '物理页';
  openDetail();
  const box = $('#detail');
  box.innerHTML = '';
  const { kind, pid } = expandPhys(st);
  const pa = (run.meta.ram_base ?? 0x80000000) + idx * (run.meta.page_size ?? 4096);
  const rows = [
    ['物理页号', String(idx)], ['物理地址', hex(pa)],
    ['归属类别', KIND_LABEL[kind[idx]]],
    ['归属进程', pid[idx] ? `pid ${pid[idx]}` : '—'],
  ];
  const mappers = [];
  for (const p of st.procs) {
    for (const [va, ppa, fl] of p.vm) {
      if (ppa === pa) mappers.push(`${run.dict.names[p.name]}(${p.pid}) va=${hex(va)}${(fl & 256) ? ' [COW]' : ''}`);
    }
  }
  rows.push(['被映射情况', mappers.length ? mappers.join('；') : '没有用户页表映射它']);
  box.appendChild(sec('物理页详情', rows));

  const hits = [];
  for (let i = 0; i < run.events.insn.length && hits.length < 40; i++) {
    const d = run.events.detail[i];
    if (!d) continue;
    if (d.pa === pa || d.old === pa || d.new === pa) {
      hits.push(i);
    }
  }
  box.appendChild(eventLinks(run, '相关事件', hits, '没有相关事件'));
}

function showProcDetail(run, st, p) {
  resetResourceDetail();
  NF.detailResourceLabel = '进程';
  openDetail();
  const box = $('#detail');
  box.innerHTML = '';
  const title = run.dict.names[p.name]
    ? `进程 ${run.dict.names[p.name]} (pid ${p.pid})`
    : `进程 pid ${plain(p.pid)}（槽位 ${plain(p.slot)}）`;
  const head = [
    ['槽位', plain(p.slot)], ['状态', p.state_name],
    ['页表根', p.pagetable === null ? '—' : hex(p.pagetable)],
    ['用户页 / COW 页 / 页表页', `${p.user_pages} / ${p.cow_pages} / ${p.pt_pages}`],
    ['父进程 pid', plain(p.parent_pid)],
  ];
  if (p.fds) head.push(['已打开 fd', p.fds.length ? p.fds.join(', ') : '（无）']);
  box.appendChild(sec(title, head));

  const fs = fieldsSec(p);
  if (fs) box.appendChild(fs);

  const rows = [];
  const upto = eventIndexAt(run, NF.cur);
  for (let i = upto; i >= 0 && rows.length < 25; i--) {
    if (run.events.pid[i] === p.pid) {
      rows.push(i);
    }
  }
  box.appendChild(eventLinks(run, '近期事件', rows, '没有相关事件'));
}

function fieldsSec(p) {
  if (!p.fields) return null;
  const names = Object.keys(p.fields).sort();
  if (!names.length) return null;

  const d = el('div', 'dsec');
  d.appendChild(el('div', 't', `进程字段（${names.length}）`));
  const kv = el('div', 'kv');
  for (const name of names) {
    const f = p.fields[name];
    const k = el('div', 'k', name);
    if (f.role && f.role !== name) {
      const b = el('span', 'role', f.role);
      b.title = `字段角色：${f.role}`;
      k.appendChild(b);
    }
    kv.appendChild(k);

    const v = el('div', 'v');
    if (f.state === 'present') {
      v.textContent = fmtFieldValue(f.value, f.reader);
    } else {
      const label = { absent: '未提供', empty: '空',
                      undecodable: '读取失败' }[f.state] || f.state;
      const tag = el('span', 'tag fs-' + f.state, label);
      if (f.reason) tag.title = f.reason;
      v.appendChild(tag);
    }
    kv.appendChild(v);
  }
  d.appendChild(kv);
  return d;
}

const IS_PTR = /\bptr\b/;

function fmtFieldValue(v, reader) {
  const one = IS_PTR.test(reader || '')
    ? (x) => (x === null || x === undefined ? '—' : hex(x))
    : (x) => (x === null || x === undefined ? '—' : (typeof x === 'number' ? plain(x) : String(x)));

  if (Array.isArray(v)) {
    if (!v.length) return '（空表）';
    const MAX = 12;
    const head = v.slice(0, MAX).map(one).join(', ');
    return v.length > MAX ? `${head} …（共 ${v.length} 项）` : head;
  }
  return one(v);
}

function sec(title, rows) {
  const d = el('div', 'dsec');
  d.appendChild(el('div', 't', title));
  const kv = el('div', 'kv');
  for (const [k, v] of rows) {
    kv.appendChild(el('div', 'k', k));
    kv.appendChild(el('div', 'v', String(v)));
  }
  d.appendChild(kv);
  return d;
}

function eventLinks(run, title, indices, emptyText = '没有相关事件') {
  const d = el('div', 'dsec');
  d.appendChild(el('div', 't', title));
  if (!indices.length) {
    d.appendChild(el('div', 'hint', emptyText));
    return d;
  }
  const list = el('div', 'related-events');
  for (const i of indices) {
    const e = evGet(run, i);
    const row = el('button', 'related-event');
    row.type = 'button';
    if (i === NF.selEvent) row.setAttribute('aria-current', 'true');
    row.appendChild(el('span', 'related-insn', fmtInsn(e.insn)));
    row.appendChild(el('span', 'related-description',
      [eventLabel(e), e.entry ? (e.entryName || e.func) : '', summarize(e)]
        .filter(Boolean).join(' · ')));
    row.onclick = () => {
      if (!$('#detail .detail-tabs') && $('#detail').contains(row)) {
        NF.detailReturn = {nodes: [...$('#detail').childNodes], insn: NF.cur, trigger: row, label: NF.detailResourceLabel}; NF.detailEventIndices = indices;
      }
      selectEvent(i);
    };
    list.appendChild(row);
  }
  d.appendChild(list);
  return d;
}


function progStates(run) {
  const ps = run.meta.program_start_insn || 0;
  const out = run.states.filter((s) => s.insn >= ps);
  return out.length ? out : run.states;
}
function progPeak(run) {
  const s = progStates(run);
  return s.length ? Math.max(...s.map((x) => x.used)) : null;
}

function forkDelta(run) {
  let idx = -1;
  const K = run.dict.kinds;
  for (let i = 0; i < run.events.insn.length; i++) {
    if (K[run.events.kind[i]] === 'vm.copy') idx = i;
  }
  if (idx < 0) return null;
  const si = stateIndexAt(run, run.events.insn[idx]);
  if (si < 0 || si + 1 >= run.states.length) return null;
  const before = run.states[si].used;
  let after = before;
  for (let j = si + 1; j < Math.min(run.states.length, si + 5); j++) {
    if (run.states[j].used > after) after = run.states[j].used;
  }
  return after - before;
}

function renderCompare() {
  const p = $('#panel-compare');
  p.innerHTML = '';
  if (NF.runs.length < 2) {
    p.appendChild(el('div', 'hint', '仅包含一次运行。'));
    return;
  }
  const [A, B] = NF.runs;
  p.appendChild(el('div', 'hint', '同一工作负载，按指令号对齐。'));

  const wrap = el('div', 'cmp');
  for (const run of NF.runs) {
    const col = el('div');
    const head = el('div', 'cmphead');
    head.innerHTML = `<b>${run.meta.run}</b><br>程序 ${run.meta.program}` +
      `　LAB_STAGE ${run.meta.lab_stage}` +
      (run.meta.make_vars && Object.keys(run.meta.make_vars).length
        ? '　' + Object.entries(run.meta.make_vars).map(([a, b]) => `${a}=${b}`).join(' ') : '');
    col.appendChild(head);
    const st = stateAt(run, NF.cur);
    const cards = el('div', 'cards');
    const c2 = (v, l) => {
      const c = el('div', 'card');
      c.appendChild(el('div', 'v', v)); c.appendChild(el('div', 'l', l)); cards.appendChild(c);
    };
    const fd = forkDelta(run);
    c2(fd === null ? '—' : (fd >= 0 ? '+' : '') + num(fd), 'fork 物理页增量');
    c2(st ? num(st.used) : '—', '当前已用物理页');
    c2(st ? num(st.shared) : '—', '当前共享页');
    c2(num(run.metrics.page_faults), '缺页异常');
    c2(num(run.metrics.kalloc), 'kalloc 次数');
    c2(fmtInsn(run.meta.total_insns), '总指令数');
    col.appendChild(cards);
    const cv = el('canvas'); cv.style.width = '100%'; cv.id = 'cmp-' + run.meta.run;
    col.appendChild(cv);
    if (st) setTimeout(() => drawPhys(cv, st, null), 0);
    wrap.appendChild(col);
  }
  p.appendChild(wrap);

  p.appendChild(el('h3', null, '关键差异'));
  const t = el('table'); const hr = el('tr');
  ['指标', A.meta.run, B.meta.run, '差值', '倍数'].forEach((h) => hr.appendChild(el('th', null, h)));
  t.appendChild(hr);
  const sa = stateAt(A, NF.cur), sb = stateAt(B, NF.cur);
  const rows = [
    ['总指令数', A.meta.total_insns, B.meta.total_insns],
    ['当前已用物理页', sa ? sa.used : null, sb ? sb.used : null],
    ['程序段峰值已用物理页', progPeak(A), progPeak(B)],
    ['fork 造成的物理页增量', forkDelta(A), forkDelta(B)],
    ['当前多进程共享页', sa ? sa.shared : null, sb ? sb.shared : null],
    ['缺页异常总数', A.metrics.page_faults, B.metrics.page_faults],
    ['kalloc 次数', A.metrics.kalloc, B.metrics.kalloc],
    ['kfree 次数', A.metrics.kfree, B.metrics.kfree],
    ['系统调用次数', A.metrics.syscalls, B.metrics.syscalls],
    ['上下文切换', A.metrics.context_switches, B.metrics.context_switches],
    ['映射区域建立（一次一段）', A.metrics.vm_maps, B.metrics.vm_maps],
    ['页表项写入（一次一个 PTE）', A.metrics.page_table_maps, B.metrics.page_table_maps],
    ['磁盘 I/O', A.metrics.disk_io, B.metrics.disk_io],
  ];
  for (const [label, x, y] of rows) {
    const tr = el('tr');
    tr.appendChild(el('td', null, label));
    tr.appendChild(el('td', 'mono', num(x)));
    tr.appendChild(el('td', 'mono', num(y)));
    const d = (x === null || y === null) ? null : y - x;
    tr.appendChild(el('td', 'mono cmpdiff', d === null ? '—' : (d > 0 ? '+' : '') + num(d)));
    let ratio = '—';
    if (x && y) ratio = (y / x).toFixed(2) + '×';
    tr.appendChild(el('td', 'mono cmpdiff', ratio));
    t.appendChild(tr);
  }
  p.appendChild(t);

  p.appendChild(el('h3', null, '目标程序阶段：物理内存'));
  p.appendChild(el('div', 'hint', '横轴：指令号。'));
  const cv = el('canvas', 'chart'); cv.style.height = '180px';
  p.appendChild(cv);
  setTimeout(() => drawChart(cv, [
    { color: '#4aa3ff', name: A.meta.run, points: progStates(A).map((s) => [s.insn, s.used]) },
    { color: '#f85149', name: B.meta.run, points: progStates(B).map((s) => [s.insn, s.used]) },
  ], {
    title: '已用物理页',
    xMin: Math.min(A.meta.program_start_insn || 0, B.meta.program_start_insn || 0),
    xMax: Math.max(A.meta.total_insns || 0, B.meta.total_insns || 0),
  }), 0);
}


function setTab(t) {
  if (NF.tab !== t && window.matchMedia('(max-width: 850px)').matches && NF.detailOpen)
    toggleDetail();
  NF.tab = t;
  $('.main').classList.toggle('debug-mode', t === 'functions');
  $('#toggle-detail').hidden = t === 'functions';
  for (const b of document.querySelectorAll('nav.tabs button')) {
    b.classList.toggle('on', b.dataset.tab === t);
    b.setAttribute('aria-current', b.dataset.tab === t ? 'page' : 'false');
  }
  for (const p of document.querySelectorAll('.panel')) {
    p.classList.toggle('on', p.id === 'panel-' + t);
  }
  render();
  if (window.matchMedia('(max-width: 850px)').matches) {
    const nav = $('nav.tabs');
    const active = nav?.querySelector('button.on');
    if (active) {
      nav.scrollLeft += active.getBoundingClientRect().left - nav.getBoundingClientRect().left
        - (nav.clientWidth - active.clientWidth) / 2;
    }
  }
}

function submitQuickFind(query) {
  const value = query.trim();
  NF.selEvent = null;
  const detail = $('#detail');
  detail.replaceChildren();
  const empty = el('div', 'detail-empty');
  empty.appendChild(el('h2', null, '详情'));
  empty.appendChild(el('p', null, '选择事件、进程或物理页。'));
  detail.appendChild(empty);
  NF.filters = { text: '', kind: '', res: '', pid: '', cpu: '', group: '', from: '', to: '' };
  const pid = /^pid\s*[:：=]\s*(\d+)$/i.exec(value);
  const insn = /^#\s*([\d,]+)$/.exec(value);
  if (pid) NF.filters.pid = pid[1];
  else if (insn) {
    const target = Number(insn[1].replaceAll(',', ''));
    if (Number.isSafeInteger(target)) NF.cur = Math.max(0, Math.min(target, NF.runs[0].meta.total_insns || target));
  } else NF.filters.text = value;
  setTab('events');
  if (insn) scrollToCurrent();
  if (window.matchMedia('(max-width: 560px)').matches) {
    requestAnimationFrame(() => $('#panel-events .result-bar')?.scrollIntoView({block: 'start'}));
  }
}

function renderDelta() {
  const box = $('#deltabar');
  if (!box) return;
  const run = NF.runs[0];
  const i = stateIndexAt(run, NF.cur);
  if (i <= 0) { box.style.display = 'none'; return; }
  const cur = run.states[i], prev = run.states[i - 1];

  const parts = [];
  const add = (label, d, unit) => {
    if (!d) return;
    const cls = d > 0 ? 'up' : 'down';
    parts.push(`${label} <span class="${cls}">${d > 0 ? '+' : ''}${num(d)}${unit || ''}</span>`);
  };
  if (cur.used !== null && prev.used !== null) add('已用物理页', cur.used - prev.used);
  if (cur.shared !== null && prev.shared !== null) add('多进程共享页', cur.shared - prev.shared);
  if (cur.procs_ok !== false && prev.procs_ok !== false)
    add('活动进程', (cur.procs || []).length - (prev.procs || []).length);

  const a = eventIndexAt(run, prev.insn), b = eventIndexAt(run, cur.insn);
  const nev = Math.max(0, b - a);
  const sampled = !!run.meta.event_selection?.dropped;

  box.style.display = '';
  box.innerHTML =
    `快照 <b>${i + 1}/${run.states.length}</b>　` +
    `区间 <b>${fmtInsn(prev.insn)} → ${fmtInsn(cur.insn)}</b>　` +
    `${sampled ? '浏览样本' : '区间事件'} <b>${num(nev)}</b> 条` +
    (parts.length ? '　｜　' + parts.join('　') : '');
}

function render() {
  const eventScroll = NF.tab === 'events' ? $('#evscroll')?.scrollTop : null;
  renderHeader();
  renderCapability();
  renderTime();
  renderDelta();
  const r = {
    overview: renderOverview, phys: renderPhys, procs: renderProcs,
    vm: renderVm, fs: renderFs, events: renderEvents, functions: renderFunctions,
    metrics: renderMetrics, console: renderConsole, compare: renderCompare,
  }[NF.tab];
  if (r) r();
  if (eventScroll != null) {
    const scroll = $('#evscroll');
    if (scroll) { scroll.scrollTop = eventScroll; scroll._paint(); }
  }
}

function toggleDetail() {
  NF.detailOpen = !NF.detailOpen;
  const main = $('.main');
  if (main) main.classList.toggle('detail-collapsed', !NF.detailOpen);
  syncDetailModal();
  if (!NF.detailOpen) {
    const trigger = NF.detailTrigger?.isConnected ? NF.detailTrigger
      : $('#evscroll tr.sel') || $('.sequence-node[aria-current="true"]') || $('nav.tabs button.on');
    trigger?.focus({preventScroll: true});
  }
  const button = $('#toggle-detail');
  if (button) {
    button.textContent = NF.detailOpen ? '收起详情' : '展开详情';
    button.setAttribute('aria-expanded', String(NF.detailOpen));
  }
}

function openDetail() {
  if (!NF.detailOpen || !document.body.classList.contains('detail-modal')) {
    const trigger = NF.pendingDetailTrigger || document.activeElement;
    NF.detailTrigger = trigger === document.body ? null : trigger;
    NF.pendingDetailTrigger = null;
  }
  if (!NF.detailOpen) toggleDetail();
  if (window.matchMedia('(max-width: 850px)').matches) {
    // Content is filled synchronously by the caller before this runs.
    requestAnimationFrame(syncDetailModal);
    requestAnimationFrame(() => $('#close-mobile-detail')?.focus({preventScroll: true}));
  }
}

function syncDetailModal() {
  const active = window.matchMedia('(max-width: 850px)').matches && NF.detailOpen && !$('#detail .detail-empty');
  document.body.classList.toggle('detail-modal', active);
  for (const node of document.querySelectorAll('.topbar, .timebar, .minimapwrap, nav.tabs, .left')) node.inert = active;
  $('.right').setAttribute('role', active ? 'dialog' : 'complementary');
  $('.right').setAttribute('aria-label', '详情');
  if (active) $('.right').setAttribute('aria-modal', 'true');
  else $('.right').removeAttribute('aria-modal');
}

function resetResourceDetail() {
  NF.detailReturn = null; NF.detailEventIndices = null; NF.detailView = 'details';
  $('.right').classList.remove('source-open');
  configureDetailBack();
}

function configureDetailBack(action = null, label = '返回列表') {
  NF.detailBack = action;
  const button = $('#close-mobile-detail');
  button.textContent = label;
  button.setAttribute('aria-label', action ? label : '关闭详情');
  button.onclick = action || toggleDetail;
}

function step(dir) {
  const run = NF.runs[0];
  const i = stateIndexAt(run, NF.cur);
  let j = i + dir;
  if (dir > 0 && i >= 0 && run.states[i].insn < NF.cur) j = i + 1;
  j = Math.max(0, Math.min(run.states.length - 1, j));
  NF.cur = run.states[j].insn;
  render();
}

function play() {
  NF.playing = !NF.playing;
  $('#play').textContent = NF.playing ? '暂停' : '播放';
  if (NF.playing) tick();
}
function tick() {
  if (!NF.playing) return;
  const run = NF.runs[0];
  const i = stateIndexAt(run, NF.cur);
  if (i + 1 >= run.states.length) {
    if (NF.loop) { NF.cur = run.states[0].insn; render(); setTimeout(tick, NF.speed); return; }
    NF.playing = false; $('#play').textContent = '播放'; return;
  }
  NF.cur = run.states[i + 1].insn;
  render();
  setTimeout(tick, NF.speed);
}

function applyUrlOptions() {
  const q = new URLSearchParams(location.search);
  NF.speed = Number(q.get('speed')) || 260;
  NF.loop = q.get('loop') === '1';
  const t = q.get('tab');
  if (t) NF.tab = t;
  if (q.get('autoplay') === '1') setTimeout(play, 600);
}

const nfExport = {
  ready: () => NF.runs.length > 0,

  info() {
    const r = NF.runs[0];
    return {
      runs: NF.runs.map((x) => x.meta.run),
      program: r.meta.program,
      kernel_kind: r.meta.kernel_kind,
      kernel_elf: r.meta.kernel_elf,
      kernel_elf_sha256: r.meta.kernel_elf_sha256,
      observed_fields: r.meta.observed_fields || {},
      event_selection: r.meta.event_selection || {},
      absent_declared: (r.meta.capability && r.meta.capability.absent_declared) || {},
      total_insns: r.meta.total_insns,
      program_start_insn: r.meta.program_start_insn || 0,
      states: r.states.length,
      events: r.events.insn.length,
      kinds: r.dict.kinds.slice(),
      outcome: r.meta.outcome,
      compare: NF.runs.length > 1,
    };
  },

  stateCount: () => NF.runs[0].states.length,
  seekState(i) {
    const s = NF.runs[0].states;
    if (!s.length) return null;
    const j = Math.max(0, Math.min(s.length - 1, i | 0));
    NF.cur = s[j].insn;
    render();
    return NF.cur;
  },
  seekInsn(n) { NF.cur = Math.max(0, Number(n) || 0); render(); return NF.cur; },
  seekFrac(f) {
    const total = NF.runs[0].meta.total_insns || 1;
    return this.seekInsn(Math.round(Math.max(0, Math.min(1, f)) * total));
  },
  seekProgFrac(f) {
    const r = NF.runs[0];
    const a = r.meta.program_start_insn || 0;
    const b = r.meta.total_insns || a;
    return this.seekInsn(a + Math.max(0, Math.min(1, f)) * (b - a));
  },

  seekBusiest() {
    const S = NF.runs[0].states;
    const ps = NF.runs[0].meta.program_start_insn || 0;
    let best = null;
    for (const s of S) {
      if (s.insn < ps) continue;
      const n = (s.procs || []).length;
      if (!best) { best = s; continue; }
      const bn = (best.procs || []).length;
      if (n > bn || (n === bn && s.used > best.used)) best = s;
    }
    if (!best) return this.seekProgFrac(0.5);
    NF.cur = best.insn; render(); return NF.cur;
  },

  tab(t) { setTab(t); return NF.tab; },
  selectPid(pid) { NF.selPid = pid === null ? null : Number(pid); render(); },

  findEvents(kind, limit) {
    const r = NF.runs[0], K = r.dict.kinds, out = [];
    const cap = limit || 50;
    for (let i = 0; i < r.events.insn.length && out.length < cap; i++) {
      if (!kind || K[r.events.kind[i]] === kind) out.push(evGet(r, i));
    }
    return out;
  },
  countEvents(kind) {
    const r = NF.runs[0], K = r.dict.kinds;
    let n = 0;
    for (let i = 0; i < r.events.insn.length; i++) if (K[r.events.kind[i]] === kind) n++;
    return n;
  },
  gotoEvent(i) {
    setTab('events');
    selectEvent(i);
    scrollToCurrent();
    return NF.cur;
  },

  settle() {
    return new Promise((res) => {
      setTimeout(() => requestAnimationFrame(() => requestAnimationFrame(() => res(true))), 0);
    });
  },
};
window.nfExport = nfExport;

const SUPPORTED_BUNDLE_FORMATS = new Set(['nodefusion.bundle/1', 'nodefusion.bundle/2']);

function prepareBundle(run) {
  if (run.format !== 'nodefusion.bundle/1') return;
  const entries = run.events.kind.reduce((count, id) =>
    count + Number((run.dict.kinds[id] || '').startsWith('func.')), 0);
  const dropped = Object.entries(run.meta.event_selection?.dropped_kinds || {})
    .reduce((count, [kind, n]) => count + (kind.startsWith('func.') ? Number(n) : 0), 0);
  run.meta.function_entries = {raw: entries + dropped, retained: entries};
}

function checkBundleFormat(run, i) {
  const f = run.format;
  const which = NF.runs.length > 1 ? `第 ${i + 1} 个数据包` : '数据包';
  if (f === undefined || f === null) {
    throw new Error(
      `${which}里没有 format 字段，认不出是哪个版本的格式。` +
      `这是很旧的包（那时还没往里写版本），重新跑一次 analyze 生成即可。`);
  }
  if (!SUPPORTED_BUNDLE_FORMATS.has(f)) {
    throw new Error(
      `${which}的格式是 ${f}，这个界面只认得 ` +
      `${[...SUPPORTED_BUNDLE_FORMATS].join('、')}。` +
      `多半是数据包比界面新 —— 用生成它的那一版 NodeFusion 重新导出页面。`);
  }
}

async function boot() {
  try {
    const nodes = document.querySelectorAll('script[type="application/nodefusion"]');
    for (const n of nodes) NF.runs.push(await inflateB64(n.textContent.trim()));
    if (!NF.runs.length) throw new Error('页面里没有找到数据包');
    NF.runs.forEach((run, i) => { checkBundleFormat(run, i); prepareBundle(run); });

    // Prefer the target start when recorded; otherwise show the busiest usable snapshot.
    const r0 = NF.runs[0];
    const ps = r0.meta.program_start_insn || 0;
    if (ps && r0.states.length) {
      const i = stateIndexAt(r0, ps);
      NF.cur = r0.states[Math.min(r0.states.length - 1, Math.max(0, i + 1))].insn;
    } else {
      const states = r0.states;
      const candidates = states.filter((s) => s.procs_ok !== false && s.procs?.length);
      const best = candidates.reduce((a, b) =>
        !a || b.procs.length > a.procs.length ||
          (b.procs.length === a.procs.length && (b.used ?? -1) > (a.used ?? -1)) ? b : a, null);
      NF.cur = best?.insn ?? (states.length ? states[Math.floor(states.length / 2)].insn
        : r0.meta.total_insns);
    }

    $('#loading').style.display = 'none';
    $('#app').style.display = 'flex';

    if (NF.runs.length < 2) {
      const b = document.querySelector('nav.tabs button[data-tab=compare]');
      if (b) b.style.display = 'none';
    } else {
      NF.tab = 'compare';
    }

    for (const b of document.querySelectorAll('nav.tabs button')) {
      if (b.dataset.tab) b.onclick = () => setTab(b.dataset.tab);
    }
    $('#nav-find').onclick = () => $('#quick-query').focus();
    $('#slider').oninput = (e) => { NF.cur = Number(e.target.value); render(); };
    $('#play').onclick = play;
    $('#prev').onclick = () => step(-1);
    $('#next').onclick = () => step(1);
    $('#quick-find').onsubmit = (e) => { e.preventDefault(); submitQuickFind($('#quick-query').value); };
    $('#toggle-detail').onclick = toggleDetail;
    $('#close-mobile-detail').onclick = toggleDetail;
    $('#minimap').onclick = (e) => {
      const r = e.target.getBoundingClientRect();
      NF.cur = Math.round(((e.clientX - r.left) / r.width) * (NF.runs[0].meta.total_insns || 1));
      render();
    };
    window.addEventListener('keydown', (e) => {
      if (e.defaultPrevented) return;
      if (document.body.classList.contains('detail-modal')) {
        if (e.key === 'Escape') { e.preventDefault(); (NF.detailBack || toggleDetail)(); return; }
        if (e.key === 'Tab') {
          const items = [...$('.right').querySelectorAll('button:not(:disabled), input:not(:disabled), select:not(:disabled), [tabindex="0"]')]
            .filter(node => node.getClientRects().length);
          const edge = e.shiftKey ? items[0] : items.at(-1);
          if (document.activeElement === edge) { e.preventDefault(); (e.shiftKey ? items.at(-1) : items[0])?.focus(); }
        }
        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') return;
      }
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault(); $('#quick-query').focus(); return;
      }
      if (e.target.closest?.('.debugger')) return;
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT' || e.target.tagName === 'BUTTON' ||
          e.target.tagName === 'TEXTAREA' || e.target.isContentEditable) return;
      if (e.key === '/') {
        $('#quick-query').focus(); e.preventDefault(); return;
      }
      if (NF.tab === 'events' && e.key.toLowerCase() === 'j') {
        navigateResults(1); e.preventDefault(); return;
      }
      if (NF.tab === 'events' && e.key.toLowerCase() === 'k') {
        navigateResults(-1); e.preventDefault(); return;
      }
      if (e.key === 'ArrowRight') { step(1); e.preventDefault(); }
      if (e.key === 'ArrowLeft') { step(-1); e.preventDefault(); }
      if (e.key === ' ') { play(); e.preventDefault(); }
    });
    window.addEventListener('resize', () => {
      syncDetailModal();
      if (NF.tab !== 'functions') { render(); return; }
      const body = $('.debug-body'), stack = $('.debug-stack'), splitter = $('.debug-splitter');
      if (!body || !stack || !splitter) return;
      const column = getComputedStyle(body).flexDirection === 'column';
      stack.style[column ? 'width' : 'height'] = '';
      splitter.setAttribute('aria-orientation', column ? 'horizontal' : 'vertical');
      splitter.setAttribute('aria-valuenow', String(column ? stack.clientHeight : stack.clientWidth));
      splitter.setAttribute('aria-valuemax', String(Math.round((column ? body.clientHeight : body.clientWidth) / 2)));
    });

    applyUrlOptions();
    setTab(NF.tab);
  } catch (err) {
    $('#loading').innerHTML = '';
    const box = el('div', 'err-box', '加载失败 · ' + shortText(err.message, 120));
    $('#loading').appendChild(box);
    console.error(err);
  }
}

document.addEventListener('DOMContentLoaded', boot);
