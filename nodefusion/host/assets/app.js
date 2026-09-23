/*
 * NodeFusion 通用可视化前端。
 *
 * 这一层刻意对"实验"一无所知：它不知道什么是写时复制、什么是 Stride 调度、
 * 什么是日志提交。它只认识数据包里的四样东西 —— 时间轴（指令号）、事件、
 * 状态快照、指标。所以换一个程序、换一个内核、换一个实验，前端一行都不用改。
 *
 * 两条核心观察路径（对应项目要求）：
 *   1. 按时间：拖动时间轴定位到某个指令/tick，看那一刻整个系统的状态。
 *   2. 按事件：在事件表里定位某次 syscall / trap / 中断 / 上下文切换 /
 *      睡眠唤醒 / 缺页 / kalloc / 页表修改 / 文件系统 / 磁盘事件，
 *      看它前后发生了什么、涉及哪些资源、造成了什么变化。
 *
 * 凡是外部观测拿不到的信息，一律显示成"未知（缺少 guest 语义）"，不编造。
 */

'use strict';

const NF = {
  runs: [],          // 一个或两个数据包（第二个用于对比）
  cur: 0,            // 当前时间：指令号
  playing: false,
  speed: 260,        // 播放时每帧停留毫秒数（录屏可用 ?speed= 调）
  loop: false,
  detailOpen: true,
  tab: 'overview',
  selEvent: null,
  selPage: null,
  selPid: null,
  filters: { text: '', kind: '', res: '', pid: '', cpu: '', group: '', from: '', to: '' },
};

/* ------------------------------------------------------------------ 工具 */

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
/* 64 位的地址和寄存器值放不进 JS 的 double。打包侧（bundle.py 的 _js_safe）
   已经把这类值发成 "0x…" 字符串了 —— 因为一旦它们以 JSON 数字的形式进来，
   `JSON.parse` 当场就把值改了，前端再格式化也是错的。
   所以这两个函数都要认字符串：原样显示，不做任何数值转换。 */
const EXACT_MAX = Number.MAX_SAFE_INTEGER;   // 2^53 - 1
const isHexStr = (n) => typeof n === 'string' && n.startsWith('0x');

const hex = (n) => {
  if (n === null || n === undefined) return '—';
  if (isHexStr(n)) return n;
  return '0x' + Number(n).toString(16);
};

const num = (n) => {
  if (n === null || n === undefined) return '—';
  // 十六进制字符串就是"大到十进制表示不精确"的那些值，照原样给。
  if (isHexStr(n)) return n;
  const v = Number(n);
  if (!Number.isFinite(v)) return '—';
  if (Math.abs(v) > EXACT_MAX) return '0x' + v.toString(16);
  return v.toLocaleString('en-US');
};

/* 整数照原样显示，取不到就是 '—'。
   跟 num() 的分工：num() 会加千位分隔符（1234 -> "1,234"），指令号、字节数
   那种大数该那样显示；pid、槽号、页数不该。
   跟 String() 的分工：String(null) 是 "null"，String(undefined) 是
   "undefined" —— 两个都会当成值印在表格里。pid 是可以为 null 的
   （ProcInfo.pid: int | None），所以这不是假想的情况。 */
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

/* ------------------------------------------------------- 状态与事件检索 */

// 找到 insn 时刻之前（含）最近的一次状态快照
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
    stack: E.stack?.[i]?.map((id) => D.funcs[id]) || null,
    tick: E.tick[i] < 0 ? null : E.tick[i],
    detail: E.detail[i], unknown: E.unknown[i],
  };
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

/* ------------------------------------------------------------ 物理内存图 */

// 归属类别配色。用户页在此基础上按 pid 微调色相，让不同进程一眼可分。
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

/*
 * 每一类归属"到底指什么"。这些是操作系统概念本身的定义，和这次跑的是什么
 * 程序、做的是哪个实验没有关系 —— 换句话说，它不会因为换个 workload 就说错。
 * 图例只给颜色和名字的话，没学过的人根本不知道自己在看什么。
 */
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
  // 游程解码成两个平铺数组
  const total = state.total;
  const kind = new Uint8Array(total);
  const pid = new Int32Array(total);
  let p = 0;
  for (const [k, pd, n] of state.phys) {
    for (let i = 0; i < n && p < total; i++, p++) { kind[p] = k; pid[p] = pd; }
  }
  return { kind, pid };
}

/*
 * prevState 给的话，会把"相对上一个快照发生了变化的页"提亮。
 * 这是让静态一帧变得可读的关键：光看一屏方块看不出名堂，
 * 但"哪些格子刚刚变了"是任何运行、任何实验都成立的通用信息。
 * 返回变化的页数，供调用方显示。
 */
/*
 * 128 MiB 里往往只有很小一块真的在用（xv6 跑个小程序常常只占 3%），
 * 整张图铺开就是一片黑，什么也看不出来。这里把**连续全空闲的整行**折叠掉，
 * 只保留有内容的行，中间用一条分隔线表示"这里跳过了 N MiB 全空闲"。
 *
 * 关键是折叠的单位是"整行"，而一行恰好是 1 MiB，所以左边的物理地址刻度
 * 依然是准确的 —— 既看得清细节，也没有骗人。
 * 规则本身与跑什么程序无关：全空就折叠，有内容就保留。
 */
function physRowPlan(state, cols, prevState) {
  const rows = Math.ceil(state.total / cols);
  const { kind } = expandPhys(state);
  const prev = prevState && prevState.total === state.total
    ? expandPhys(prevState).kind : null;

  const busy = new Uint8Array(rows);
  for (let r = 0; r < rows; r++) {
    for (let i = r * cols; i < Math.min(state.total, (r + 1) * cols); i++) {
      // 本帧非空闲，或者上一帧非空闲（刚被释放的行也值得看见）
      if (kind[i] !== 0 || (prev && prev[i] !== 0)) { busy[r] = 1; break; }
    }
  }
  // 有内容的行前后各留一行余量，避免贴边看着突兀
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
    // 只折叠够长的空段，省下来的高度才值得多一条分隔线
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

  // fold=false 时退化成"整块 128 MiB 全画"，两种视图共用同一段绘制逻辑
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
        /*
         * 变化标记要分方向，否则一次大规模释放会把半张图拉成灰白，
         * 反而看不出剩下的页各自是什么。
         *   刚被占用 → 往白拉一点（保留原色相，还认得出变成了什么）
         *   刚被释放 → 压成暗红（贴近空闲的深色，只是留个"这里刚空出来"的痕迹）
         */
        if (kind[i] === 0) { r = 74; g = 32; b = 36; }
        else { r += (255 - r) * 0.38; g += (255 - g) * 0.38; b += (255 - b) * 0.38; }
      }
      img.data[o] = r; img.data[o + 1] = g; img.data[o + 2] = b; img.data[o + 3] = 255;
    }
  }
  ctx.putImageData(img, 0, 0);
  // 点击要能从"屏幕上第几行"反推回"物理内存第几页"，所以把行计划一起存下来
  canvas._nfphys = { kind, pid, cols, total, lines };
  return changed;
}

/* ---------------------------------------------------------------- 小地图 */

function drawMinimap(run) {
  const c = $('#minimap');
  const w = c.clientWidth || 900, h = 34;
  c.width = w; c.height = h;
  const ctx = c.getContext('2d');
  ctx.fillStyle = '#161b22'; ctx.fillRect(0, 0, w, h);
  const total = run.meta.total_insns || 1;

  // 事件密度直方图
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

  // 快照刻度
  ctx.fillStyle = '#3fb950';
  for (const s of run.states) {
    const x = Math.floor((s.insn / total) * w);
    ctx.fillRect(x, 0, 1, 4);
  }

  // 关键事件标注（panic / 缺页 / 上下文切换）
  const marks = { 'kernel.panic': '#f85149', 'trap.page_fault': '#d29922' };
  for (let i = 0; i < E.length; i++) {
    const k = run.dict.kinds[run.events.kind[i]];
    const col = marks[k];
    if (col) {
      const x = Math.floor((E[i] / total) * w);
      ctx.fillStyle = col; ctx.fillRect(x, h - 4, 1, 4);
    }
  }

  // 目标程序开始执行的分界线（由校准跑测出的最后一次 exec）
  const ps = run.meta.program_start_insn;
  if (ps) {
    const x = Math.floor((ps / total) * w);
    ctx.fillStyle = '#a371f7';
    ctx.fillRect(x, 0, 1, h);
    ctx.fillStyle = '#a371f7'; ctx.font = '9px sans-serif';
    ctx.fillText('程序开始', Math.min(w - 48, x + 3), 10);
  }

  // 播放头
  const px = Math.floor((NF.cur / total) * w);
  ctx.fillStyle = '#4aa3ff';
  ctx.fillRect(px, 0, 1, h);
}

/* ---------------------------------------------------------------- 折线图 */

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

/* ------------------------------------------------------------------ 渲染 */

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
    boot_failed: '启动失败', qemu_exited: 'QEMU 提前退出',
  }[m.outcome] || m.outcome;
}

function renderCapability() {
  const run = NF.runs[0];
  const c = run.meta.capability;
  const box = $('#capability');
  const items = [];
  const compact = (value, limit = 140) => shortText(value, limit);
  items.push(c.nftrace_records
    ? `内核语义：${num(c.nftrace_records)} 条 nftrace`
    : '内核语义：未启用 nftrace');
  if (c.missing_watch_functions && c.missing_watch_functions.length) {
    const names = c.missing_watch_functions.slice(0, 4).join('、');
    items.push(`缺少观察点：${num(c.missing_watch_functions.length)} 个${names ? `（${names}${c.missing_watch_functions.length > 4 ? '…' : ''}）` : ''}`);
  }
  if (c.missing_layout_fields && c.missing_layout_fields.length) {
    items.push(`缺少字段：${num(c.missing_layout_fields.length)} 个`);
  }
  if (c.trace_truncated_at_eof) items.push('轨迹在结尾截断');
  if (c.plugin_truncated) items.push('物理内存快照在结尾截断');
  if (run.meta.event_selection && run.meta.event_selection.dropped) {
    const s = run.meta.event_selection;
    items.push(`事件流：${num(s.retained)} / ${num(s.raw)} 条（${s.policy} 抽样）`);
  }
  for (const [kind, d] of Object.entries(c.absent_declared || {})) {
    const why = d.why === 'feature' ? '内核没有这项功能' : '内核有该行为但缺少所需观测粒度';
    items.push(`${kind}：${why}`);
  }
  for (const n of run.meta.notes || []) items.push(compact(n));
  for (const wn of run.meta.warnings || []) items.push(`告警 @${fmtInsn(wn.insn)}：${compact(wn.text)}`);

  const cov = c.coverage || null;
  const metric = cov && cov.metrics;
  const complete = cov && cov.status === 'complete';
  const headline = cov
    ? (complete
        ? `100% 可适用覆盖 · 指标 ${metric.covered}/${metric.applicable}`
        : `覆盖未完整 ${num(cov.percent)}% · 指标 ${metric.covered}/${metric.applicable} · `
          + `${num((cov.blockers || []).length)} 类待解决`)
    : '观测能力';

  box.style.display = 'flex';
  box.className = 'capability ' + (complete ? 'coverage-complete' : 'coverage-incomplete');
  box.innerHTML = '';
  const disclosure = el('details', 'cap-disclosure');
  const summary = el('summary');
  summary.appendChild(el('span', 'cap-headline', headline));
  summary.appendChild(el('span', 'cap-more', '详情'));
  disclosure.appendChild(summary);
  const ul = el('ul');
  for (const t of items) ul.appendChild(el('li', null, t));
  if (cov && cov.blockers && cov.blockers.length) {
    ul.appendChild(el('li', null, '机器审计未通过：' +
      cov.blockers.map((b) => b.check).join('、')));
  }
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
    `快照 <b>${si >= 0 ? si : '—'}</b>/${run.states.length}`;
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
  /*
   * 每个累计数都配一条"平均多久发生一次"。
   * 光看"缺页异常 38,243"没人判断得了这是多还是少，但"平均每 21.6 万条指令一次"
   * 是个能直接感受的密度。分母是总指令数，任何运行都有，不需要知道跑的是什么。
   */
  /*
   * 哪些卡片上的数是 `@rN` 抽稀过的（#154）。这份对应关系不在这儿维护 ——
   * analyze.py 的 `_METRIC_KINDS` 已经写死了"指标名 -> 事件类别"，
   * `sampling.metrics` 就是拿它跟观察点上的 rate 交出来的结果。
   */
  const smet = (m.sampling || {}).metrics || {};
  const tagOf = (name) => {
    const r = smet[name];
    if (!r || !r.length) return '';
    const hi = r.filter((x) => x > 1);
    // 同一类挂了好几个观察点、限流还不一样，那这个数既不是全量也不是干净的
    // 1/N，只能说"部分"。
    return r.some((x) => x <= 1) ? ` · 1/${hi.join('、1/')}`
                                 : ` · 1/${hi.join('、1/')}`;
  };
  /*
   * 每个累计数都配一条"平均多久发生一次"。
   * 光看"缺页异常 38,243"没人判断得了这是多还是少，但"平均每 21.6 万条指令一次"
   * 是个能直接感受的密度。分母是总指令数，任何运行都有，不需要知道跑的是什么。
   *
   * 抽样过的那些不给密度。分子少了 N 倍，除出来的密度就稀了 N 倍 ——
   * "平均每 21M 条指令一次 kalloc"是个具体、好记、错了两个数量级的印象。
   * 乘回去也不行：N 是上限不是实测（末尾不足 N 次的余数直接丢），
   * 那样得出的是估算，不是量出来的。
   */
  const hiRate = (name) => {
    const r = smet[name];
    if (!r || !r.length) return 0;
    const hi = Math.max(...r);
    return hi > 1 ? hi : 0;
  };
  const rate = (n, name) => {
    // 抽样过的不给密度，给区间。密度是拿计数当分子算的，分子少了 N 倍，
    // 算出来的"平均每 21M 条指令一次"就是个具体、好记、错两个数量级的印象。
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
  // JS 里 null - null === 0，直接相减会把"两个都测不到"变成"净分配 0 页"，
  // 那是编出来的数。任一侧不可观测，差值就没有意义。
  //
  // 抽样过的那一侧同理，而且更阴（#154）：`kalloc 57 / kfree 53` 两个都是
  // 1/256 抽样，差出来的 4 不是"净分配 4 页"—— 真实净值大约是它的 256 倍，
  // 而两个独立抽样的差本身就是噪声，256 倍之后噪声也跟着放大。数字看着小、
  // 精确、可信，结论却是错的，比显示"未知"糟得多。
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
  // 命中率是 (缓存读 − 设备读) / 缓存读 —— 一个**差**除以一个数。两个分量各自
  // 抽样之后这个式子就废了，哪怕限流一样：
  //
  //   Starry 这趟缓存读记 3 条、设备读记 1 条；两边都是 1/64，`3 - 1`
  //   仍然不是两次命中。真实值落在两个区间里，不能由样本点相减得到。
  //
  // 比值"分子分母同除以 N 所以还在"那套说法只在数大的时候成立。这里不成立，
  // 而且不成立的时候恰好会给出一个特别像结论的数（0.0%）。所以只要有一侧
  // 抽样过就不给百分比 —— 这是三态里的"测不准"，跟"测出来是 0"不一样。
  const hrSampled = !!(smet.bcache_reads || smet.disk_io);
  const hrSub = m.cache_hit_accounting === 'unverified'
    ? `缓存请求 ${num(m.bcache_reads)} · 磁盘 I/O ${num(m.disk_io)}`
    : hrSampled ? '样本不可合并' : `${num(m.bcache_hits)} / ${num(m.bcache_reads)} 次缓存请求`;
  card((m.bcache_hit_rate === null || hrSampled)
         ? '—' : (m.bcache_hit_rate * 100).toFixed(1) + '%',
       '缓存命中率', hrSub);
  // 映射分两档，**按粒度不按内核**：区域级一次调用映一段（xv6 mappages、
  // ArceOS Backend::map），页级一次调用写一个 PTE（rCore PageTable::map）。
  // 两档以前共用一张卡片，于是 76583 和 32318 并排摆着看，而那是「映射了
  // 多少段」对「写了多少个 PTE」。标题得把粒度写出来，不然分开也白分。
  // 这几张卡的副标题是**粒度说明**不是密度，所以区间得另外接上去，不能走
  // `rate()`（那个是拿副标题的位置说密度的）。
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
  p.appendChild(cards);

  if (m.cache_hit_accounting === 'one_to_one')
    p.appendChild(el('div', 'hint', '缓存命中率按缓存请求与设备读取次数计算。'));

  // 上面若干张卡片显示 "—"，是因为这个内核里压根没有对应的函数可挂观测点。
  // 不写清楚的话，"—" 和 "0" 在读者眼里都是"没发生"，而这两件事完全不同。
  if (m.unobservable_reason) {
    const d = el('details', 'inline-disclosure hint');
    d.appendChild(el('summary', null, '指标不可用'));
    d.appendChild(el('div', 'disclosure-body', shortText(m.unobservable_reason, 90)));
    p.appendChild(d);
  }

  // 当前时刻的系统概况
  p.appendChild(el('h3', null, '当前时刻的系统状态'));
  if (!st) {
    p.appendChild(el('div', 'hint', '此时刻无物理内存快照。'));
  } else {
    const g = el('div', 'cards');
    const c2 = (v, l) => {
      const c = el('div', 'card');
      c.appendChild(el('div', 'v', v)); c.appendChild(el('div', 'l', l));
      g.appendChild(c);
    };
    c2(num(st.free), '空闲物理页');
    c2(num(st.used), '已用物理页');
    c2(num(st.shared), '多进程共享页');
    // 进程表解不出来时这三项是"不知道"，不是 0。num(null) 会显示 "—"。
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
  // 解不出进程表时给一句明确的话。空表格会被读成"当前没有进程"，
  // 那是个结论；这里没有结论。
  if (st.procs_ok === false) {
    return el('div', 'err-box',
      '进程表不可用 · ' + shortText(st.procs_reason || '未知原因', 110));
  }
  // 列分两段。
  //
  // **结构列**是解码器自己算出来的，不在任何一份 manifest 里：slot 是它在数组
  // 里的下标，三个页数是**走页表数出来的**。每个内核都有，写死在这里是对的。
  // pid / 名字 / 状态也放这一段 —— 它们的来源是 manifest 字段，但解码器已经
  // 按 role（id / name / state）把它们认出来并归一化过了，下游一直用的是归一
  // 化后的那个值（比如 arceos 的 state 读出来是 2，state_name 才是名字）。
  //
  // **字段列**从 `p.fields` 来，也就是 manifest 里声明了什么就显示什么。以前
  // 这里写死的是 xv6 那 14 列，于是 rCore 上 chan / 优先级 / stride / pass 四
  // 列恒为 '—'（它没有这些东西），同时它自己的 base / children / trapcx 一列
  // 都看不到；而 xv6 自己的 killed / kstack / cwd / has_mail 也从来没露过面。
  const structural = [
    ['slot', (p) => plain(p.slot), 'mono'],
    ['pid', (p) => plain(p.pid), null],
  ];
  // 名字这一列跟着数据走。rCore 的 TaskControlBlock 里没有名字这个字段（进程
  // 叫什么写在 ELF 里，不在 TCB 里），整列都是 '—' —— 那一列什么也没说。
  if (st.procs.some((p) => run.dict.names[p.name])) {
    structural.push(['名字', (p) => run.dict.names[p.name] || '—', null]);
  }
  // 父进程用**解出来的 pid**，不是指针。下面的字段列里还会有一个 `parent`
  // （xv6 是 ptr，rCore 是 option<weak>），那是内核里存的原样；这一列是
  // NodeFusion 顺着它查到的是哪个进程。两个都留着：前者是事实，后者是结论。
  if (st.procs.some((p) => p.parent_pid !== null && p.parent_pid !== undefined)) {
    structural.push(['父进程', (p) => plain(p.parent_pid), null]);
  }
  const cols = [];
  // 字段列的顺序 = manifest 里的声明顺序（JSON 对象保序）。取并集是因为同一
  // 趟里不同进程可能少几个字段（读失败），少的那个不该把整列吃掉。
  const seen = new Map();
  for (const p of st.procs) {
    for (const k of Object.keys(p.fields || {})) {
      if (!seen.has(k)) seen.set(k, p.fields[k].role || null);
    }
  }
  // role 已经在结构列里露过面的字段不再重复一列（xv6 的 pid、rCore 的 status）。
  const shownRoles = new Set(['id', 'name', 'state']);
  const fieldKeys = [...seen.keys()].filter((k) => !shownRoles.has(seen.get(k)));

  // 整列都是 absent 的，说明这个内核压根没有这个字段 —— 少一列，并把原因写在
  // 表下面。空着一列比少一列更糟：读的人分不清"没有这个概念"和"这次没读到"。
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
    // 老解码器不发 fields。那时候只剩结构列，说一句，别让人以为这个内核的
    // 进程只有这么点信息。
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

/* manifest 字段的一格（连 <td> 一起造，因为 absent 那种要挂 title）。
   `state` 有三种，显示上必须分得开：
     present —— 读到了，按 reader 决定怎么印
     empty   —— 读到了，是空的（空指针 / None）。印 '（空）'，不是 '—'
     absent  —— 这个内核没有这个字段。印 '—'，鼠标停上去是 manifest 给的原因
   把后两种都印成 '—' 的话，"这里没有东西"和"我们没看到"就混成了一句话。 */
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
  // 指针类按十六进制。用 reader 和 role 判断，不猜数值大小 —— 大小是个坏判据：
  // xv6 的 sz 也能到几十万，那不是地址。
  //
  // role 那半边是必要的：rCore 的 task_cx 读法是 `struct`（读出来的是这个结构
  // 体的地址），reader 上看不出它是地址，可 role = sched_context 说得很清楚。
  // 少了这一条它会印成 2,183,300,240 —— 一个加了千位分隔符的地址。
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

  const base = run.meta.ram_base || 0x80000000;
  const psz = run.meta.page_size || 4096;
  const cols = 256;                       // 每行 256 页
  const rowBytes = cols * psz;            // 每行正好 1 MiB —— 这让地址刻度变得好读
  const rows = Math.ceil(st.total / cols);

  p.appendChild(el('div', 'hint',
    `每格 ${psz / 1024} KiB · ${num(st.total)} 页 · ${rowBytes / 1048576} MiB / 行 · 点击查看页详情` +
    (st.pt_root_src === 'observed-satp' ? ' · 地址空间来自 satp 观测' : '') +
    (!st.pt_root_src ? ' · 未观测到页表根' : '') +
    (st.phys_reason ? ` · ${shortText(st.phys_reason, 120)}` : '')));

  // 图例：颜色 + 名字 + 这个名字到底指什么。术语解释是操作系统概念本身，
  // 和这次跑的是什么程序无关，所以放在这里是安全的。
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

  // 折叠开关：默认折叠掉全空闲的整行，否则小程序在 128 MiB 里根本看不见
  const bar = el('div', 'physopt');
  const cb = el('input'); cb.type = 'checkbox'; cb.id = 'foldchk';
  cb.checked = NF.foldPhys !== false;
  cb.onchange = () => { NF.foldPhys = cb.checked; renderPhys(); };
  const lb = el('label'); lb.htmlFor = 'foldchk';
  lb.textContent = '折叠全空闲区域（只看真正在用的内存）';
  bar.appendChild(cb); bar.appendChild(lb);
  p.appendChild(bar);

  // 画布 + 左侧地址刻度。刻度做成 HTML 而不是画进 canvas：
  // canvas 是 256×N 的原始像素再被 CSS 拉伸的，在上面画字会糊成一团。
  const wrap = el('div', 'physwrap');
  const axis = el('div', 'physaxis');
  const cv = el('canvas'); cv.id = 'physcanvas';
  cv._nffold = NF.foldPhys !== false;
  wrap.appendChild(axis);
  wrap.appendChild(cv);
  p.appendChild(wrap);

  // 和上一个快照比：变了的页会被提亮，这样一眼能看出"刚刚哪里动了"
  const si = stateIndexAt(run, NF.cur);
  const prevSt = si > 0 ? run.states[si - 1] : null;
  const changed = drawPhys(cv, st, NF.selPid, prevSt);

  // 地址刻度跟着实际画出来的行走：每个连续数据段的开头标一次，
  // 折叠段标出跳过了多少。这样刻度在两种视图下都是准的。
  const lines = cv._nfphys.lines;
  /*
   * 间距要按"屏幕上隔了几行"算，不能按"物理地址差了多少"算：
   * 折叠之后一行可能只有几个像素高，两个标签会直接叠在一起（踩过）。
   * 折叠标记优先显示（不标就不知道跳过了多少），地址标签给它让位。
   */
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
  p.appendChild(el('div', 'hint',
    (prevSt ? `变化页 ${num(changed)}` : '') +
    (folded ? ` · 折叠空闲 ${folded} 行` : '')));

  // 卡片：每个绝对数都配一个参照系，否则"31,763"这种数字没法判断大小
  const g = el('div', 'cards');
  const c2 = (v, l, sub) => {
    const c = el('div', 'card');
    c.appendChild(el('div', 'v', v));
    c.appendChild(el('div', 'l', l));
    if (sub) c.appendChild(el('div', 's', sub));
    g.appendChild(c);
  };
  const pct = (x) => ((x / st.total) * 100).toFixed(1) + '%';
  // 单位自适应：11 页写成 "0.0 MiB" 等于没说，小量要退回 KiB
  const mib = (x) => {
    const k = x * psz / 1024;
    return k >= 1024 ? (k / 1024).toFixed(1) + ' MiB' : num(k) + ' KiB';
  };
  // 数值为 null 表示这一项本次拿不到（比如没有空闲链表就不知道空闲页数）。
  // 这时候连参照系一起换成说明，绝不能让 pct/mib 算出 NaN 冒充一个数。
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

// 相对上一个快照的变化量。纯减法，不解释含义。
function deltaStr(prev, cur, field) {
  if (!prev) return '';
  // 任一端拿不到就没有差值可言 —— null 参与减法会算出 NaN
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

  p.appendChild(el('h3', null, '各核当前进程'));
  if (!st.cpus.length) {
    // 空表配一排 xv6 的表头（push_off 深度 / 中断使能）是在暗示"这些量存在，
    // 只是这一刻没有" —— 而 rCore 和 ArceOS 根本没有 xv6 那个 per-CPU 结构。
    // 一行都没有的时候就别画表。
    p.appendChild(el('div', 'hint', '未重建 per-CPU 运行表。'));
  } else {
    const t = el('table');
    const hr = el('tr');
    ['CPU', 'pid', '进程', 'push_off 深度', '中断使能'].forEach((h) => hr.appendChild(el('th', null, h)));
    t.appendChild(hr);
    for (const c of st.cpus) {
      const tr = el('tr');
      tr.appendChild(el('td', null, String(c.cpu)));
      tr.appendChild(el('td', null, c.pid === null ? '（调度器）' : String(c.pid)));
      tr.appendChild(el('td', null, run.dict.names[c.name] || '—'));
      // num() 认 null 也认 undefined。String(c.noff) 在读不到时会印出 "null"，
      // 那看着像个值。
      tr.appendChild(el('td', 'mono', num(c.noff)));
      tr.appendChild(el('td', 'mono', num(c.intena)));
      t.appendChild(tr);
    }
    p.appendChild(t);
  }

  // 等待与同步：谁睡在哪个 chan 上。
  //
  // 'SLEEPING' 是 **xv6 的**状态名。rCore 的状态叫 Ready / Running / Zombie，
  // ArceOS 的又是另一套，两边都永远匹配不上，于是这一栏对它们恒定地说
  // "当前没有进程处于睡眠状态" —— 那是一句**关于内核的断言**，而且没有任何
  // 观测支持它：我们不是量到没人睡，是压根没在这个内核的词汇里找过。
  const sleepers = st.procs.filter((x) => x.state_name === 'SLEEPING');
  const states = [...new Set(st.procs.map((x) => x.state_name).filter(Boolean))];
  const hasSleepState = states.includes('SLEEPING');
  p.appendChild(el('h3', null, '等待与同步关系'));
  if (!hasSleepState && st.procs.length) {
    p.appendChild(el('div', 'hint', `当前内核未提供 xv6 chan 字段（状态：${states.join('、')}）。`));
  } else if (!sleepers.length) {
    p.appendChild(el('div', 'hint', '当前没有进程处于睡眠状态。'));
  } else {
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
      // 在事件流里回溯最近一次 wakeup(chan)
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
  for (const [va, pa, fl] of pr.vm) {
    const tr = el('tr', 'clickable');
    tr.appendChild(el('td', 'mono', hex(va)));
    tr.appendChild(el('td', 'mono', hex(pa)));
    tr.appendChild(el('td', 'mono', String(Math.floor((pa - 0x80000000) / 4096))));
    tr.appendChild(el('td', 'mono', perms(fl)));
    let note = '';
    if (fl & 256) note = '写时复制：只读共享，写入会触发缺页并复制';
    else if (!(fl & 16)) note = '内核侧映射（trampoline / trapframe）';
    tr.appendChild(el('td', null, note));
    tr.onclick = () => {
      const idx = Math.floor((pa - 0x80000000) / 4096);
      NF.selPage = idx; showPageDetail(run, st, idx);
    };
    t.appendChild(tr);
  }
  p.appendChild(t);
}

function renderFs() {
  const run = NF.runs[0];
  const p = $('#panel-fs');
  p.innerHTML = '';
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

  // 一格怎么显示由 manifest 的 format 说了算，不由列名猜。以前这三张表的
  // 每一格都写死在下面：`r.valid ? '是' : '否'`、`hex(r.inode)`、`num(r.size)`。
  // 换个内核就得在这里再加一段，而漏加不会报错 —— 只是少一张表。
  const cell = (v, c) => {
    if (v === null || v === undefined) return '—';   // 没读到，不是 0
    switch (c.format) {
      case 'bool': return v ? '是' : '否';
      case 'hex':  return hex(v);
      case 'num':  return num(v);
      default:     return String(v);
    }
  };

  // 资源表全部来自 st.resources —— 表名、列、顺序都在数据里，这里一个内核的
  // 名字都不出现。以前 xv6 的 bcache/ftable/itable 三张表的列名写死在这段
  // 代码里，第二个内核想显示自己的表就得再加一段。
  const resources = st.resources || [];
  if (!resources.length) {
    // 空有两种成因，结论相反：内核确实没有资源表，还是我们压根没去看。
    // 后端把原因带上来了，照发。
    p.appendChild(el('div', 'hint',
                     shortText(st.resources_reason || '该内核没有可显示的资源表。')));
  }
  for (const res of resources) {
    // show_when_any：默认只铺"在用"的行。这是**内核的判断**，写在 manifest
    // 里；界面照做，不自己拟规则。列表为空就全铺。
    const keys = res.show_when_any || [];
    const rows = keys.length
      ? (res.rows || []).filter((r) => keys.some((k) => r[k]))
      : (res.rows || []);
    section(res.label || res.name, { ok: res.ok, reason: res.reason, rows },
            (res.columns || []).map((c) => c.label),
            (r) => (res.columns || []).map((c) => cell(r[c.key], c)),
            res.empty || '当前没有内容。');
    // 少掉的可选列要说出来。默默少一列的话，读的人会以为这个内核就没这项。
    for (const n of res.notes || []) {
      p.appendChild(el('div', 'hint', shortText(n)));
    }
  }

  // 这个内核有没有"打开文件表"这个概念，看的是数据里有没有 fds，不是看内核
  // 叫什么名字。rCore 和 ArceOS 的 open_fds 是 null（ProcInfo 里就允许），
  // 一整张表全是 null 的时候画出来只有一列 '—'，不如说清楚为什么没有。
  const anyFds = st.procs.some((pr) => pr.fds);
  p.appendChild(el('h3', null, '每进程文件描述符'));
  if (!anyFds) {
    p.appendChild(el('div', 'hint', '未记录每进程 fd 表。'));
  } else {
    const t = el('table'); const hr = el('tr');
    ['进程', 'pid', '已打开的 fd'].forEach((h) => hr.appendChild(el('th', null, h)));
    t.appendChild(hr);
    for (const pr of st.procs) {
      const tr = el('tr');
      tr.appendChild(el('td', null, run.dict.names[pr.name]));
      tr.appendChild(el('td', null, plain(pr.pid)));
      // pr.fds 可以是 null —— 直接 .length 会抛 TypeError，把整个资源面板
      // 打断在半截（前面的资源表已经画出来了，后面的什么都没有，而且没有
      // 任何报错提示）。解不出来（'—'）和解出来是空的（'（无）'）要分开。
      tr.appendChild(el('td', 'mono',
        !pr.fds ? '—' : (pr.fds.length ? pr.fds.join(', ') : '（无）')));
      t.appendChild(tr);
    }
    p.appendChild(t);
  }
}

/* ---------------------------------------------------------------- 事件表 */

let evFiltered = [];

function applyFilters() {
  const run = NF.runs[0];
  const f = NF.filters;
  const n = run.events.insn.length;
  evFiltered = [];
  const txt = f.text.trim().toLowerCase();
  const from = f.from === '' ? null : Number(f.from);
  const to = f.to === '' ? null : Number(f.to);
  for (let i = 0; i < n; i++) {
    const insn = Number(run.events.insn[i]);
    if (from !== null && Number.isFinite(from) && insn < from) continue;
    if (to !== null && Number.isFinite(to) && insn > to) continue;
    const kind = run.dict.kinds[run.events.kind[i]];
    if (f.kind && kind !== f.kind) continue;
    if (f.group && eventGroup(kind) !== f.group) continue;
    if (f.res && run.dict.res[run.events.res[i]] !== f.res) continue;
    if (f.pid !== '' && String(run.events.pid[i]) !== f.pid) continue;
    if (f.cpu !== '' && String(run.events.cpu[i]) !== f.cpu) continue;
    if (txt) {
      const fn = run.dict.funcs[run.events.func[i]] || '';
      const d = run.events.detail[i];
      const hay = (kind + ' ' + (run.dict.res[run.events.res[i]] || '') + ' ' + fn + ' ' +
                   (d ? JSON.stringify(d) : '')).toLowerCase();
      if (hay.indexOf(txt) < 0) continue;
    }
    evFiltered.push(i);
  }
}

function renderEvents() {
  const run = NF.runs[0];
  const p = $('#panel-events');
  p.innerHTML = '';

  const heading = el('div', 'section-heading');
  const title = el('div');
  title.appendChild(el('h2', null, '事件浏览器'));
  title.appendChild(el('div', 'section-subtitle', '筛选事件，点击行定位。'));
  heading.appendChild(title);
  const shortcut = el('span', 'shortcut-hint', '按 / 聚焦搜索');
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
  const searchWrap = el('label', 'filter-control filter-search');
  searchWrap.appendChild(el('span', 'filter-label', '搜索'));
  const selection = run.meta.event_selection || {};
  const sampled = !!selection.applied && selection.dropped > 0;
  const kinds = [...new Set(run.dict.kinds)].sort();
  const kSel = el('select');
  kSel.appendChild(new Option('全部事件类型', ''));
  for (const k of kinds) {
    const kept = (selection.retained_kinds || {})[k] || 0;
    const raw = kept + ((selection.dropped_kinds || {})[k] || 0);
    kSel.appendChild(new Option(sampled ? `${k} · ${num(kept)} / ${num(raw)}` : k, k));
  }
  kSel.value = NF.filters.kind;
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

  const tIn = el('input'); tIn.id = 'event-search'; tIn.type = 'search'; tIn.placeholder = '函数名、参数、系统调用…';
  tIn.value = NF.filters.text;
  tIn.oninput = () => updateTextFilter('text', tIn);
  searchWrap.appendChild(tIn);

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
  clear.onclick = () => { clearTimeout(NF.filterTimer); NF.filters = { text: '', kind: '', res: '', pid: '', cpu: '', group: '', from: '', to: '' }; renderEvents(); };

  const groupWrap = el('label', 'filter-control');
  groupWrap.appendChild(el('span', 'filter-label', '语义分组'));
  groupWrap.appendChild(groupSel);
  f.appendChild(searchWrap); f.appendChild(groupWrap); f.appendChild(kindWrap); f.appendChild(resWrap); f.appendChild(pidWrap); f.appendChild(cpuWrap);
  f.appendChild(fromWrap); f.appendChild(toWrap); f.appendChild(jump); f.appendChild(clear);
  p.appendChild(f);

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
  p.appendChild(presets);

  applyFilters();
  const info = el('div', 'result-bar');
  info.appendChild(el('strong', null, `${num(evFiltered.length)} 条结果`));
  info.appendChild(el('span', null, sampled
    ? ` / ${num(run.events.insn.length)} 条浏览样本 · 原始 ${num(selection.raw)} 条`
    : ` / ${num(run.events.insn.length)} 条事件`));
  if (NF.filters.kind || NF.filters.group || NF.filters.res || NF.filters.pid || NF.filters.cpu || NF.filters.text || NF.filters.from || NF.filters.to) {
    info.appendChild(el('span', 'result-active', '已应用筛选'));
  }
  p.appendChild(info);
  if (!evFiltered.length) {
    const empty = el('div', 'event-empty');
    empty.appendChild(el('strong', null, sampled ? '样本中没有匹配事件' : '没有匹配的事件'));
    empty.appendChild(el('p', null, '清除筛选或调整范围。'));
    p.appendChild(empty);
    return;
  }

  const facet = el('div', 'event-facets');
  const counts = new Map();
  for (let i = 0; i < run.events.insn.length; i++) {
    const k = run.dict.kinds[run.events.kind[i]];
    counts.set(k, (counts.get(k) || 0) + 1);
  }
  [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 8).forEach(([kind, count]) => {
    const b = el('button', 'facet' + (NF.filters.kind === kind ? ' selected' : ''));
    b.type = 'button'; b.title = sampled
      ? `筛选 ${kind} · 原始 ${num(count + ((selection.dropped_kinds || {})[kind] || 0))} 条`
      : `筛选 ${kind}`;
    b.appendChild(el('span', null, kind)); b.appendChild(el('b', null, num(count)));
    b.onclick = () => { NF.filters.kind = NF.filters.kind === kind ? '' : kind; renderEvents(); };
    facet.appendChild(b);
  });
  if (facet.childElementCount) p.appendChild(facet);

  const density = el('div', 'event-density');
  const densityHead = el('div', 'density-head');
  densityHead.appendChild(el('div', 'density-label', sampled ? '样本事件分布' : '事件分布'));
  const bars = el('div', 'density-bars');
  const bins = 48; const totalInsn = Number(run.meta.total_insns) || 1; const binCounts = Array(bins).fill(0);
  for (const i of evFiltered) {
    const at = Math.min(bins - 1, Math.floor(Number(run.events.insn[i]) / totalInsn * bins));
    binCounts[at]++;
  }
  const peak = Math.max(1, ...binCounts);
  densityHead.appendChild(el('span', 'density-meta', `每段 ${axisNum(totalInsn / bins)} 指令 · 峰值 ${num(peak)}`));
  density.appendChild(densityHead);
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
  ['指令号', 'tick', 'CPU', 'pid', '事件', '资源', '函数', '要点'].forEach((h) => hr.appendChild(el('th', null, h)));
  table.appendChild(hr);
  const body = el('tbody'); table.appendChild(body);
  scroll.appendChild(table);
  p.appendChild(scroll);

  // 简易虚拟滚动：只渲染视口附近的行
  const ROW = 34;
  const spacerTop = el('tr'); const tdT = el('td'); tdT.colSpan = 8; spacerTop.appendChild(tdT);
  const spacerBot = el('tr'); const tdB = el('td'); tdB.colSpan = 8; spacerBot.appendChild(tdB);

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
      tr.setAttribute('aria-label', `${e.kind}，指令 ${fmtInsn(e.insn)}，${summarize(e)}`);
      if (NF.selEvent === i) tr.className += ' sel';
      tr.appendChild(el('td', 'mono', fmtInsn(e.insn)));
      tr.appendChild(el('td', 'mono', e.tick === null ? '—' : String(e.tick)));
      tr.appendChild(el('td', 'mono', String(e.cpu)));
      tr.appendChild(el('td', 'mono', e.pid === null ? '—' : String(e.pid)));
      const kindCell = el('td'); kindCell.appendChild(el('span', 'event-kind', e.kind)); tr.appendChild(kindCell);
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
    case 'syscall.enter': return `${d.syscall}(${(d.args || []).slice(0, 3).map(hex).join(', ')})`;
    case 'trap.page_fault': return `${d.fault_kind} @ ${hex(d.fault_va)}`;
    case 'trap.exception': return d.cause_name || '';
    case 'interrupt.timer': case 'interrupt.external': return d.cause_name || '';
    // 名字缺了**不等于**是调度器。原来这里两端都兜底成"调度器"，那是 xv6 的
    // 推理（它的 proc[64] 是定长数组，枚举得全，查不到就只能是 &c->context）。
    // 换到枚举不全的内核上，同一个兜底就成了编造：ArceOS 上确实有只在切换参数
    // 里露过面、枚举够不着的任务，全被这句话说成了调度器。
    //
    // 现在"是调度器"由分析那边判定后写进 from_proc / to_proc，这里只管照印。
    // 真不知道的时候印"?"，理由在 detail 的 from_unknown / to_unknown 里，
    // 点开这条事件就能看到 —— 这一格是纯文本，塞不进 tooltip。
    case 'sched.switch': {
      const side = (n) => n == null || n === '' ? '?' : String(n);
      return `${side(d.from_proc)} → ${side(d.to_proc)}`;
    }
    case 'phys.free': return hex(d.pa);
    case 'phys.alloc':
      // 有 guest 语义时内核会直接报出分配到哪一页；没有就照实说外部看不到
      if (d.allocated_pa === 0) return '分配失败（物理内存耗尽）';
      if (d.allocated_pa) return '分配一页 ' + hex(d.allocated_pa);
      return '分配一页（返回值外部不可见）';
    case 'pagetable.map': return `va=${hex(d.va)} pa=${hex(d.pa)} 大小=${num(d.size)} 权限=${hex(d.perm)}`;
    case 'pagetable.unmap': return `va=${hex(d.va)} ${num(d.npages)} 页`;
    case 'vm.copy': return `父页表=${hex(d.old)} 子页表=${hex(d.new)} 大小=${num(d.sz)}`;
    case 'bcache.read': case 'bcache.get': return `dev=${d.dev} block=${d.blockno}`;
    case 'bcache.result': return `${d.outcome || '?'} · block=${d.first_block} · ${num(d.blocks)} 块`;
    case 'disk.io': return d.write ? '写盘' : '读盘';
    case 'sync.sleep': return `chan=${hex(d.chan)}`;
    case 'sync.wakeup': return `chan=${hex(d.chan)}`;
    case 'kernel.panic': return d.msg || 'panic';
    case 'inode.get': return `dev=${d.dev} inum=${d.inum}`;
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

function selectEvent(i) {
  const previousScroll = $('#evscroll')?.scrollTop;
  NF.selEvent = i;
  NF.cur = NF.runs[0].events.insn[i];
  render();
  const scroll = $('#evscroll');
  if (scroll && previousScroll !== undefined) { scroll.scrollTop = previousScroll; scroll._paint(); }
  showEventDetail(NF.runs[0], i);
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
    ? ` · 显示 ${num(entryCounts.retained)} / ${num(entryCounts.raw)} 条`
    : '';
  const returns = run.meta.function_returns || { raw: 0, matched: 0, nested_entries: 0 };
  title.appendChild(el('div', 'section-subtitle', returns.raw
    ? `函数入口${scope} · ${num(returns.matched)} / ${num(returns.raw)} 条返回匹配观测帧`
    : `函数入口${scope} · 返回地址可定位直接调用方；本次未录制返回事件。`));
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
    entries.push({ i, fn, caller, path, insn: run.events.insn[i], cpu: run.events.cpu[i], pid: run.events.pid[i] });
  }
  if (!entries.length) {
    const empty = el('div', 'event-empty');
    empty.appendChild(el('strong', null, '无函数入口事件'));
    empty.appendChild(el('p', null, '前往事件浏览器。'));
    p.appendChild(empty);
    return;
  }

  const controls = el('div', 'trace-controls');
  const search = el('input'); search.type = 'search'; search.placeholder = '筛选函数名'; search.id = 'function-search';
  const cpu = el('select'); cpu.id = 'function-cpu'; cpu.appendChild(new Option('全部 CPU', ''));
  for (const c of [...new Set(entries.map((e) => e.cpu))].sort((a, b) => a - b)) cpu.appendChild(new Option(`CPU ${c}`, String(c)));
  const limit = el('select'); limit.id = 'function-limit';
  for (const n of [40, 80, 160]) limit.appendChild(new Option(`最近 ${n} 条`, String(n)));
  limit.value = '80';
  const grouping = el('select'); grouping.id = 'function-grouping';
  grouping.appendChild(new Option('调用关系', 'caller'));
  grouping.appendChild(new Option('名称层级', 'namespace'));
  if (returns.nested_entries) grouping.appendChild(new Option('观测调用链', 'stack'));
  if (returns.nested_entries) grouping.value = 'stack';
  else if (!entries.some((e) => e.caller)) grouping.value = 'namespace';
  controls.appendChild(search); controls.appendChild(cpu); controls.appendChild(grouping);
  controls.appendChild(limit); p.appendChild(controls);

  const grid = el('div', 'trace-grid');
  const treePanel = el('section', 'trace-panel');
  const treeTitle = el('div', 'trace-panel-title', '调用关系');
  const treeNote = el('div', 'trace-panel-note', '由入口时的返回地址定位直接调用方。');
  treePanel.appendChild(treeTitle);
  treePanel.appendChild(treeNote);
  const sequencePanel = el('section', 'trace-panel');
  sequencePanel.appendChild(el('div', 'trace-panel-title', '入口顺序'));
  sequencePanel.appendChild(el('div', 'trace-panel-note', '按记录顺序排列。'));
  const tree = el('div', 'function-tree'); const sequence = el('div', 'function-sequence');
  treePanel.appendChild(tree); sequencePanel.appendChild(sequence);
  grid.appendChild(treePanel); grid.appendChild(sequencePanel); p.appendChild(grid);

  function paint() {
    const q = search.value.trim().toLowerCase();
    const selectedCpu = cpu.value;
    const filtered = entries.filter((e) => (!q || e.fn.toLowerCase().includes(q) || e.caller.toLowerCase().includes(q) || (e.path || []).some((name) => name.toLowerCase().includes(q))) && (selectedCpu === '' || String(e.cpu) === selectedCpu));
    const counts = new Map();
    for (const e of filtered) counts.set(e.fn, (counts.get(e.fn) || 0) + 1);
    tree.innerHTML = '';
    if (grouping.value === 'stack') {
      treeTitle.textContent = '观测调用链';
      treeNote.textContent = '入口与返回匹配的帧；中断、任务切换和缺失观察点会截断链。';
      const chains = new Map();
      for (const e of filtered) {
        if (!e.path || e.path.length < 2) continue;
        const key = e.path.join('\0');
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
          row.onclick = () => { setTab('events'); selectEvent(chain.index); };
          tree.appendChild(row);
        });
      if (!chains.size) tree.appendChild(el('div', 'trace-muted', '当前筛选中没有可匹配的嵌套帧。'));
    } else if (grouping.value === 'caller') {
      treeTitle.textContent = '调用关系';
      treeNote.textContent = '由入口时的返回地址定位直接调用方。';
      const edges = new Map();
      for (const e of filtered) {
        if (!e.caller) continue;
        const key = `${e.caller}\0${e.fn}`;
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
          row.onclick = () => { setTab('events'); selectEvent(edge.index); };
          tree.appendChild(row);
        });
      if (!edges.size) tree.appendChild(el('div', 'trace-muted', '这些入口的返回地址无法定位调用方。'));
    } else {
    treeTitle.textContent = '名称层级';
    treeNote.textContent = '按命名空间聚合，数字为次数。';
    const root = { label: '', count: 0, children: new Map(), fn: null };
    const partsOf = (fn) => fn.split(/::|[\\/]/).filter(Boolean).slice(0, 8);
    for (const [fn, count] of counts) {
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
        if (child.children.size && depth < 2) {
          const children = el('div', 'function-children');
          children.hidden = depth > 0;
          row.onclick = () => { children.hidden = !children.hidden; row.firstChild.textContent = `${children.hidden ? '› ' : '⌄ '}${child.label}`; };
          parent.appendChild(children);
          paintNode(child, depth + 1, children);
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
    filtered.slice(-cap).forEach((e, index, arr) => {
      if (index) sequence.appendChild(el('div', 'sequence-link'));
      const node = el('button', 'sequence-node'); node.type = 'button'; node.title = '定位到这条入口事件';
      node.appendChild(el('span', 'sequence-index', String(index + 1).padStart(2, '0')));
      node.appendChild(el('span', 'sequence-function', e.fn));
      node.appendChild(el('span', 'sequence-meta', `${fmtInsn(e.insn)} · CPU ${e.cpu}${e.path?.length > 1 ? ` · ${e.path.join(' → ')}` : e.caller ? ` · ${e.caller} →` : ''}`));
      node.onclick = () => selectEvent(e.i);
      sequence.appendChild(node);
    });
    if (!filtered.length) sequence.appendChild(el('div', 'trace-muted', '没有匹配的入口事件。'));
  }
  search.oninput = paint; cpu.onchange = paint; grouping.onchange = paint;
  limit.onchange = paint; paint();
}

/* ---------------------------------------------------------------- 指标图 */

function renderMetrics() {
  const run = NF.runs[0];
  const m = run.metrics;
  const p = $('#panel-metrics');
  p.innerHTML = '';
  p.appendChild(el('div', 'hint', '横轴：指令号。曲线来自运行记录。'));

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

  // 已用页数要靠内核的空闲链表，共享页数要靠进程表；这两样在有些内核上
  // 解不出来（rCore 就是），那时整条曲线全是 null。画个空框子没有意义，
  // 直接说明为什么没有。
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

  // 累计计数曲线
  const cum = (pred) => {
    const pts = []; let n = 0;
    const E = run.events;
    for (let i = 0; i < E.insn.length; i++) {
      if (pred(run.dict.kinds[E.kind[i]])) { n++; pts.push([E.insn[i], n]); }
    }
    if (!pts.length) pts.push([0, 0]);
    return pts;
  };
  /* 指标为 null = 这个内核里没有对应函数可挂观测点。这时候画出来的是一条
     贴着 0 的直线，看的人只会读成"这件事一次都没发生" —— 那是假的。
     没有观测手段就不画，改成一行说明。 */
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
  // 一张表里三件事，别让它们长得一样（#90）：
  //
  //   有数     这趟响了 N 次。
  //   0 次     观察点挂上了，一次没响 —— **量出来的 0**。换个负载可能就有。
  //   没有     manifest 声明本内核没有这件事，附了依据。换十个负载也不会有。
  //
  // 少掉中间那一档的话，"这趟没发生"会跟"没人映射它"一样只是表里少一行，
  // 而这两句该让人做的事正好相反。老 run 的 HTML 里没有这两个字段，所以
  // 下面都带兜底 —— 拿旧数据打开新界面，退化成只有第一档，不该炸。
  p.appendChild(el('div', 'hint', '0 次 = 已观测；— = 未观测。抽样项显示区间。'));
  // 全趟被限流丢掉的命中数。插件那边留这个计数器的原话是"没有这个数，抽稀过
  // 的事件流和本来就稀疏的事件流在报告里分不出来"。null = 这趟没记（旧轨迹）,
  // 跟 0（一条没丢）不是一回事，所以只在有数的时候说。
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

  // 末位收可变个数的标记：抽样的类别要挂两个（"1/N 抽样" + 实际区间）。
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

  // 抽样过的类别（#154）。插件的 `@rN:` 是"每 N 次命中才写一条"，所以这一行
  // 的次数不是真实次数 —— 而它长得跟真计数一模一样。不打标的话，`phys.alloc
  // 57` 会被读成"这趟分配了 57 页"，真实值可以高到 14592。
  //
  // **给区间，不给点值**。14592 = 57×256 是**上界**，站得住；把它当成"分配了
  // 14592 页"就站不住了 —— 末尾不足 N 次的余数会被丢，一类还可能挂着好几个
  // 观察点各记各的。所以写成 `57` 加一句"实际 57～14592"：两端都是算出来的，
  // 中间那个最像答案的数反倒是唯一不能说的。
  const sampled = (run.metrics.sampling || {}).kinds || {};
  const sampleTag = (k) => {
    const rates = sampled[k];
    if (!rates || !rates.length) return null;
    const hi = rates.filter((r) => r > 1);
    const mixed = rates.some((r) => r <= 1);
    const tag = el('span', 'tag why-empty',
      mixed ? `部分 1/${hi.join('、1/')} 抽样` : `1/${hi.join('、1/')} 抽样`);
    tag.title = mixed
      ? '这一类挂了好几个观察点，限流不一样：一部分每次都记，一部分每 N 次记'
      + '一条。所以这个数既不是全量，也不是干净的 1/N —— 别拿它跟别的数比。'
      : `每 ${hi[0]} 次命中才写一条。`
      + `记下 n 条，真实次数就在 n 和 n×${hi[0]} 之间 —— 这是个界，不是估算。`;
    return tag;
  };
  // 抽样类别的真实次数区间。**上界是算出来的，不是估的**：插件那边
  // `__atomic_fetch_add` 返回的是**旧值**，所以第一次命中 n=0、`0 % rate == 0`，
  // 一定记；此后每 N 次记一条。于是记下 k 条 ⟹ 真实命中在 [k, k×N] 之间。
  //
  // 两个推论，都跟界面上的说法有关：
  //   * **0 条就是真的没发生**。第一次命中必记，所以"挂了没响"那一栏
  //     即使被抽样过，说"这趟没发生"仍然是对的 —— 不用改。
  //   * 不写点值。区间是量出来的，`k×N` 那个点值不是（末尾不足 N 次的余数
  //     会被丢，而且一类可能挂着好几个观察点，各有各的计数器）。
  const sampleRange = (k, v) => {
    const r = sampled[k];
    if (!r || !r.length) return null;
    const hi = Math.max(...r);
    if (hi <= 1) return null;
    const s = el('span', 'dim', ` 实际 ${num(v)}～${num(v * hi)}`);
    s.title = '区间的两端都是算出来的：每条记录对应至少一次真实命中（下界），'
      + `每 ${hi} 次命中至多记一条（上界）。`;
    return s;
  };

  const ent = Object.entries(run.metrics.by_kind).sort((a, b) => b[1] - a[1]);
  for (const [k, v] of ent) {
    const tr = row(k, num(v), 'clickable', sampleTag(k), sampleRange(k, v));
    tr.onclick = () => { NF.filters.kind = k; setTab('events'); };
  }
  for (const k of (run.metrics.armed_silent || [])) {
    // 仍然可点：跳过去看到一个空列表，正是"挂了没响"的样子。
    const tag = el('span', 'tag why-empty', '这趟没发生');
    const tr = row(k, '0', 'clickable k-silent', tag);
    tr.onclick = () => { NF.filters.kind = k; setTab('events'); };
  }
  const absent = run.metrics.absent_declared || {};
  for (const k of Object.keys(absent).sort()) {
    // 不可点 —— 点过去永远是空的，而那个空跟"这趟没发生"的空含义不同。
    const why = absent[k].why;
    const tag = el('span', 'tag why-' + why,
      why === 'feature' ? '本内核没有' : '没有对得上的粒度');
    tag.title = absent[k].evidence || '';
    row(k, '—', 'k-absent', tag);
  }
  p.appendChild(t);
}

function renderConsole() {
  const run = NF.runs[0];
  const p = $('#panel-console');
  p.innerHTML = '';
  p.appendChild(el('div', 'hint',
    'guest 串口输出。'));
  const pre = el('pre', 'console', run.meta.console || '(没有控制台输出)');
  p.appendChild(pre);
}

/* -------------------------------------------------------------- 右侧详情 */

function showEventDetail(run, i) {
  const box = $('#detail');
  box.innerHTML = '';
  const e = evGet(run, i);

  box.appendChild(sec('选中的事件', [
    ['事件类型', e.kind], ['资源', e.res], ['指令号', fmtInsn(e.insn)],
    ['tick', e.tick === null ? '—' : String(e.tick)], ['CPU', String(e.cpu)],
    ['进程', e.pid === null ? '—' : `pid ${e.pid}`],
    ['PC', hex(e.pc)],
    // 用户态地址在内核符号表里当然查不到 —— 这不是"解析失败"，要说清楚，
    // 否则会被误读成工具出了问题。
    ['函数', e.func || (e.pc && e.pc < 0x80000000 ? '用户态' : '—')],
    ['观测调用链', e.stack?.length > 1 ? e.stack.join(' → ') : '—'],
  ]));

  if (e.detail && Object.keys(e.detail).length) {
    const rows = Object.entries(e.detail).map(([k, v]) => {
      if (Array.isArray(v)) return [k, v.map(hex).join(', ')];
      // 打包侧发过来的 "0x…" 字符串就是超出 double 精度的 64 位值，只给十六进制。
      if (isHexStr(v)) return [k, v];
      // 十六进制永远给；十进制只在能精确表示时才附上，否则那个括号里的数是假的。
      if (typeof v === 'number' && v > 4096) {
        return [k, Math.abs(v) > EXACT_MAX ? hex(v) : `${hex(v)} (${num(v)})`];
      }
      return [k, String(v)];
    });
    box.appendChild(sec('事件参数', rows));
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
    box.appendChild(d);
  }

  // 事件前后的系统变化
  const si = stateIndexAt(run, e.insn);
  if (si >= 0 && si + 1 < run.states.length) {
    const a = run.states[si], b = run.states[si + 1];
    const rows = [];
    const cmp = (label, va, vb) => {
      // 任一端不可知就只显示 "— → —"，不给差值 —— null 相减会得到 NaN
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
    box.appendChild(sec(
      `快照 ${si} → ${si + 1}`,
      rows));
    box.appendChild(el('div', 'hint', '事件所在快照之间的变化。'));
  }

  // 邻近事件
  const near = [];
  for (let k = Math.max(0, i - 6); k < Math.min(run.events.insn.length, i + 7); k++) {
    const x = evGet(run, k);
    near.push([fmtInsn(x.insn), (k === i ? '▶ ' : '') + x.kind + ' ' + summarize(x)]);
  }
  box.appendChild(sec('相邻事件', near));
}

function showPageDetail(run, st, idx) {
  const box = $('#detail');
  box.innerHTML = '';
  const { kind, pid } = expandPhys(st);
  const pa = 0x80000000 + idx * 4096;
  const rows = [
    ['物理页号', String(idx)], ['物理地址', hex(pa)],
    ['归属类别', KIND_LABEL[kind[idx]]],
    ['归属进程', pid[idx] ? `pid ${pid[idx]}` : '—'],
  ];
  // 哪些进程把它映射进了自己的地址空间
  const mappers = [];
  for (const p of st.procs) {
    for (const [va, ppa, fl] of p.vm) {
      if (ppa === pa) mappers.push(`${run.dict.names[p.name]}(${p.pid}) va=${hex(va)}${(fl & 256) ? ' [COW]' : ''}`);
    }
  }
  rows.push(['被映射情况', mappers.length ? mappers.join('；') : '没有用户页表映射它']);
  box.appendChild(sec('物理页详情', rows));

  // 该页相关的事件
  const hits = [];
  for (let i = 0; i < run.events.insn.length && hits.length < 40; i++) {
    const d = run.events.detail[i];
    if (!d) continue;
    if (d.pa === pa || d.old === pa || d.new === pa) {
      const e = evGet(run, i);
      hits.push([fmtInsn(e.insn), e.kind + ' ' + summarize(e)]);
    }
  }
  box.appendChild(sec('与这一页相关的事件', hits.length ? hits : [['—', '这次运行里没有直接提到这一页的事件']]));
}

function showProcDetail(run, st, p) {
  const box = $('#detail');
  box.innerHTML = '';
  // 这一段只留**解码器自己算出来的**东西：槽位、走页表数出来的三个页数、
  // 顺着父指针查到的 pid。字段本身（sz / chan / killed / xstate / 优先级…）
  // 交给下面的 fieldsSec —— 那一段按 manifest 走，内核有什么显示什么。
  //
  // 以前这里照 xv6 的 struct proc 写死了十行，于是 rCore 上"等待通道"
  // "killed / xstate""优先级 / stride / pass"四行恒为 '—'：xv6 没有的东西
  // 它一行都不少地列着，而 rCore 自己的 base / trapcx / children 一行都没有。
  const title = run.dict.names[p.name]
    ? `进程 ${run.dict.names[p.name]} (pid ${p.pid})`
    : `进程 pid ${plain(p.pid)}（槽位 ${plain(p.slot)}）`;
  const head = [
    ['槽位', plain(p.slot)], ['状态', p.state_name],
    ['页表根', p.pagetable === null ? '—' : hex(p.pagetable)],
    ['用户页 / COW 页 / 页表页', `${p.user_pages} / ${p.cow_pages} / ${p.pt_pages}`],
    ['父进程 pid', plain(p.parent_pid)],
  ];
  // p.fds 可以是 null（这个内核没有打开文件表），.length 会直接抛。
  // 而且 null 的时候这一行本身就不该出现 —— 它问的问题不适用。
  if (p.fds) head.push(['已打开 fd', p.fds.length ? p.fds.join(', ') : '（无）']);
  box.appendChild(sec(title, head));

  const fs = fieldsSec(p);
  if (fs) box.appendChild(fs);

  const rows = [];
  const upto = eventIndexAt(run, NF.cur);
  for (let i = upto; i >= 0 && rows.length < 25; i--) {
    if (run.events.pid[i] === p.pid) {
      const e = evGet(run, i);
      rows.push([fmtInsn(e.insn), e.kind + ' ' + summarize(e)]);
    }
  }
  box.appendChild(sec('这个进程最近的事件（从当前时刻往前）',
    rows.length ? rows : [['—', '当前时刻之前没有归属到该进程的事件']]));
}

/* manifest 声明的**全部**字段，带状态。

   上面那一段是写死的一张表：哪些字段、叫什么、怎么排，都是照 xv6 的 struct
   proc 写的。manifest 里多声明一个字段（xv6 自己的 has_mail 就是），它落不到
   任何一行上，于是解出来了也没人看得见。这一段不认字段名，manifest 里有什么
   就显示什么。

   现在两段**并排显示**是有意的：这一段将来要取代上面那一段，并排的时候能直接
   对出哪里不一致 —— 跟新旧解码器对拉是同一个办法。等界面全改成读这条通道，
   上面那段和 bundle 里的老键一起删。

   老的分内核解码器不产生这条通道（p.fields 是 undefined），那时候整段不显示，
   而不是显示一段空的 —— 空的会被读成"manifest 一个字段都没声明"。 */
function fieldsSec(p) {
  if (!p.fields) return null;
  const names = Object.keys(p.fields).sort();
  if (!names.length) return null;

  const d = el('div', 'dsec');
  d.appendChild(el('div', 't', `字段（manifest 通道，共 ${names.length} 项）`));
  const kv = el('div', 'kv');
  for (const name of names) {
    const f = p.fields[name];
    const k = el('div', 'k', name);
    // 角色跟字段名一样的时候不重复显示（xv6 的 name/name、state/state）——
    // 印成 "name name" 只是噪声。pgtbl/address_space_root 这种才有信息。
    if (f.role && f.role !== name) {
      const b = el('span', 'role', f.role);
      b.title = `角色：${f.role} —— 跨内核通用的概念，界面靠它找字段，不靠字段名`;
      k.appendChild(b);
    }
    kv.appendChild(k);

    const v = el('div', 'v');
    if (f.state === 'present') {
      v.textContent = fmtFieldValue(f.value, f.reader);
    } else {
      // 三种"没值"用不同的标签，理由挂在 title 上 —— 界面上要能一眼看出
      // 哪个是故障（undecodable），哪些是正常的没有。
      const label = { absent: '内核没有', empty: '空',
                      undecodable: '解不出来' }[f.state] || f.state;
      const tag = el('span', 'tag fs-' + f.state, label);
      if (f.reason) tag.title = f.reason;
      v.appendChild(tag);
    }
    kv.appendChild(v);
  }
  d.appendChild(kv);
  return d;
}

/* 按 manifest 声明的类型印一个值。

   `reader` 是 manifest 里那一行写的（"ptr" / "i32" / "array<ptr>"）。指针
   要十六进制：0x80233e80 一眼是内核地址，2149793408 得先换算才知道是同一个
   数。这里**不按字段名判断** —— "叫 chan 的大概是指针"就是把内核细节又写回
   界面代码，而这正是这次移植要去掉的东西。

   \bptr\b 而不是 indexOf('ptr')：要匹配 "ptr" 和 "array<ptr>"（尖括号是非
   单词字符，边界成立），但不能被将来某个含 ptr 字母的包装名误伤。 */
const IS_PTR = /\bptr\b/;

function fmtFieldValue(v, reader) {
  const one = IS_PTR.test(reader || '')
    ? (x) => (x === null || x === undefined ? '—' : hex(x))
    : (x) => (x === null || x === undefined ? '—' : (typeof x === 'number' ? plain(x) : String(x)));

  if (Array.isArray(v)) {
    if (!v.length) return '（空表）';
    // 每个元素单独印：join() 会把 null 变成空串，于是 [a,null] 印成 "a, "，
    // 空槽看着像排版毛病而不是"这个槽没东西"。
    const MAX = 12;
    const head = v.slice(0, MAX).map(one).join(', ');
    // 截断了必须说出来。默默少几项就是这个项目要防的那种输出。
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

/* ---------------------------------------------------------------- 对比页 */

// 只看目标程序开始之后的快照。启动阶段（kinit 逐页释放物理内存）会产生一个
// 与实验无关的巨大峰值，把它算进来会让两次运行的对比失去意义。
function progStates(run) {
  const ps = run.meta.program_start_insn || 0;
  const out = run.states.filter((s) => s.insn >= ps);
  return out.length ? out : run.states;
}
function progPeak(run) {
  const s = progStates(run);
  return s.length ? Math.max(...s.map((x) => x.used)) : null;
}

// fork 这一下到底多花了多少物理页：取 uvmcopy 发生前最后一个快照的已用页数，
// 与其后若干快照内的最大值之差。这是"有没有写时复制"最直接的可观测后果。
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

  // 差值表
  p.appendChild(el('h3', null, '关键差异'));
  const t = el('table'); const hr = el('tr');
  ['指标', A.meta.run, B.meta.run, '差值', '倍数'].forEach((h) => hr.appendChild(el('th', null, h)));
  t.appendChild(hr);
  const sa = stateAt(A, NF.cur), sb = stateAt(B, NF.cur);
  const rows = [
    ['总指令数', A.meta.total_insns, B.meta.total_insns],
    ['当前已用物理页', sa ? sa.used : null, sb ? sb.used : null],
    // 注意：这里刻意只统计目标程序开始之后的峰值。整次运行的全局峰值出现在启动早期
    // （kinit 还没把物理页释放完），那个数字和实验本身没有关系，拿来对比会误导。
    ['程序段峰值已用物理页', progPeak(A), progPeak(B)],
    ['fork 造成的物理页增量', forkDelta(A), forkDelta(B)],
    ['当前多进程共享页', sa ? sa.shared : null, sb ? sb.shared : null],
    ['缺页异常总数', A.metrics.page_faults, B.metrics.page_faults],
    ['kalloc 次数', A.metrics.kalloc, B.metrics.kalloc],
    ['kfree 次数', A.metrics.kfree, B.metrics.kfree],
    ['系统调用次数', A.metrics.syscalls, B.metrics.syscalls],
    ['上下文切换', A.metrics.context_switches, B.metrics.context_switches],
    // 两档分开列。并成一行的话，拿区域级的内核跟页级的内核对比时，
    // 表里会出现「76583 对 32318」这种看着能比、其实不能比的一行。
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

/* ------------------------------------------------------------------ 主控 */

function setTab(t) {
  NF.tab = t;
  for (const b of document.querySelectorAll('nav.tabs button')) {
    b.classList.toggle('on', b.dataset.tab === t);
    b.setAttribute('aria-current', b.dataset.tab === t ? 'page' : 'false');
  }
  for (const p of document.querySelectorAll('.panel')) {
    p.classList.toggle('on', p.id === 'panel-' + t);
  }
  render();
}

/*
 * 变化摘要条：只回答"相对上一个快照，这一刻有什么变了"。
 * 全部是两个快照相减得到的事实，不猜测这些变化是为了什么 ——
 * 那属于学生自己该连起来的部分，也是这个工具刻意不替他做的部分。
 */
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
  add('已用物理页', cur.used - prev.used);
  add('多进程共享页', cur.shared - prev.shared);
  add('活动进程', (cur.procs || []).length - (prev.procs || []).length);

  // 这两个快照之间发生了多少条事件 —— 衡量"这一段忙不忙"
  const a = eventIndexAt(run, prev.insn), b = eventIndexAt(run, cur.insn);
  const nev = Math.max(0, b - a);

  box.style.display = '';
  box.innerHTML =
    `快照 <b>${i + 1}/${run.states.length}</b>　` +
    `区间 <b>${fmtInsn(prev.insn)} → ${fmtInsn(cur.insn)}</b>　` +
    `本区间事件 <b>${num(nev)}</b> 条` +
    (parts.length ? '　｜　' + parts.join('　') : '　｜　状态无变化');
}

function render() {
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
}

function toggleDetail() {
  NF.detailOpen = !NF.detailOpen;
  const main = $('.main');
  if (main) main.classList.toggle('detail-collapsed', !NF.detailOpen);
  const button = $('#toggle-detail');
  if (button) {
    button.textContent = NF.detailOpen ? '收起详情' : '展开详情';
    button.setAttribute('aria-expanded', String(NF.detailOpen));
  }
}

function step(dir) {
  const run = NF.runs[0];
  // 按快照步进：一次跳到下一个/上一个有完整状态的时刻
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

/*
 * 录屏用的播放控制。做成 URL 参数是为了让"打开就自动播放"变得可脚本化：
 * 直接把带参数的地址丢给 PowerPoint 的屏幕录制或任意录屏工具即可，
 * 不需要人工点按钮。
 *   ?autoplay=1        打开即播放
 *   ?speed=400         每帧停留毫秒数
 *   ?loop=1            播完循环
 *   ?tab=phys          打开时停在指定页签
 */
function applyUrlOptions() {
  const q = new URLSearchParams(location.search);
  NF.speed = Number(q.get('speed')) || 260;
  NF.loop = q.get('loop') === '1';
  const t = q.get('tab');
  if (t) NF.tab = t;
  if (q.get('autoplay') === '1') setTimeout(play, 600);
}

/*
 * ------------------------------------------------------- 录像导出用的接口
 *
 * `?autoplay=1` 那条路径是给人肉录屏用的：它按墙钟时间播放，录出来的帧
 * 依赖机器当时快不快。做 PPT 素材需要的是另一种东西 —— **确定性**：
 * 同一份运行记录，无论在哪台机器上导出多少次，第 N 帧必须一模一样。
 *
 * 所以这里把"时间推进"和"画面渲染"拆开，交给外部逐帧驱动：
 * 导出器调 seek 系列 / `tab` / `gotoEvent` 摆好状态，await `settle()` 等这一帧画完，
 * 截图，再走下一帧。没有任何计时器参与，帧率完全由导出器决定。
 *
 * 这一层同样对"实验"一无所知：它只暴露时间轴、页签、事件三种通用抓手。
 */
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

  // 时间定位。三种粒度，外部按需选：快照序号 / 指令号 / 全程比例。
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
  // 目标程序执行区间内的比例定位 —— 启动段每次都一样，做素材通常要跳过。
  seekProgFrac(f) {
    const r = NF.runs[0];
    const a = r.meta.program_start_insn || 0;
    const b = r.meta.total_insns || a;
    return this.seekInsn(a + Math.max(0, Math.min(1, f)) * (b - a));
  },

  /*
   * 定位到"系统最忙的那个快照"：活动进程最多，并列时取已用物理页最多的。
   * 用途是别让画面停在空系统上 —— 程序刚启动和刚退出的时刻，进程表是空的、
   * 内存也是空的，拿来做静态展示等于什么都没显示。
   * 规则本身是纯数据的：不需要知道跑的是什么程序，任何运行都算得出来。
   */
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

  // 事件定位：先按类型找，再跳过去。返回的下标可以直接喂给 gotoEvent。
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

  /*
   * 等这一帧真正画完。画布类内容（物理内存图、指标曲线）是在 render() 里用
   * setTimeout(...,0) 排出去的，render() 返回时它们还没画。所以这里必须
   * 先放掉一个宏任务，再等两帧 rAF，让布局和绘制都落地，截图才不会拍到空白。
   */
  settle() {
    return new Promise((res) => {
      setTimeout(() => requestAnimationFrame(() => requestAnimationFrame(() => res(true))), 0);
    });
  },
};
window.nfExport = nfExport;

/* 认得的数据包格式。跟 host/nftrace.py 的 SUPPORTED_FORMAT_VERS 是同一件事：
   读之前先问一句"这个格式我认不认得"。

   以前这里一句都不问 —— bundle.py 一直在 `format` 里写版本号，前端从来没读
   过。于是换格式的时候，一个旧的 app.js（浏览器缓存里那份、别人存下来的那份
   HTML）会照着旧字段去读新数据包：字段不在就是 undefined，undefined 一路渲染
   成 '—'。**整页都能正常打开**，只是里面的数每一个都是空的，而且没有任何地方
   说出过一句"这份数据我读不了"。

   所以对不上就抛，让加载整个失败。宁可打不开，也不要打开了给人看一屏假的。 */
// 只认 /2。/1 的资源表是 bcache/ftable/itable 三个固定键，这一版的界面读不了
// —— 与其画出三张空表，不如直接说版本对不上。已经渲染好的旧报告不受影响：
// 每份 HTML 自带那一版 app.js。
const SUPPORTED_BUNDLE_FORMATS = new Set(['nodefusion.bundle/2']);

function checkBundleFormat(run, i) {
  const f = run.format;
  const which = NF.runs.length > 1 ? `第 ${i + 1} 个数据包` : '数据包';
  if (f === undefined || f === null) {
    // 没写版本跟版本不认识是两回事：前者是 2026-08 之前打的包，后者是将来的包。
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
    // 在任何东西读 meta 之前先校验：读过之后再报错，屏幕上已经有半页假数据了。
    NF.runs.forEach(checkBundleFormat);

    // 默认停在"目标程序刚开始执行"那一刻：启动过程每次都一样，没什么好看的；
    // 停在最后一帧则程序已经退出，系统又空了。这个位置是通用的，
    // 和具体跑的是什么程序无关。
    const r0 = NF.runs[0];
    const ps = r0.meta.program_start_insn || 0;
    if (ps && r0.states.length) {
      const i = stateIndexAt(r0, ps);
      NF.cur = r0.states[Math.min(r0.states.length - 1, Math.max(0, i + 1))].insn;
    } else {
      NF.cur = r0.states.length ? r0.states[r0.states.length - 1].insn
                                : r0.meta.total_insns;
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
      b.onclick = () => setTab(b.dataset.tab);
    }
    $('#slider').oninput = (e) => { NF.cur = Number(e.target.value); render(); };
    $('#play').onclick = play;
    $('#prev').onclick = () => step(-1);
    $('#next').onclick = () => step(1);
    $('#quick-events').onclick = () => setTab('events');
    $('#toggle-detail').onclick = toggleDetail;
    $('#minimap').onclick = (e) => {
      const r = e.target.getBoundingClientRect();
      NF.cur = Math.round(((e.clientX - r.left) / r.width) * (NF.runs[0].meta.total_insns || 1));
      render();
    };
    window.addEventListener('keydown', (e) => {
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT') return;
      if (e.key === '/' && NF.tab === 'events') {
        const search = $('#event-search');
        if (search) { search.focus(); e.preventDefault(); }
      }
      if (e.key === 'ArrowRight') { step(1); e.preventDefault(); }
      if (e.key === 'ArrowLeft') { step(-1); e.preventDefault(); }
      if (e.key === ' ') { play(); e.preventDefault(); }
    });
    window.addEventListener('resize', () => render());

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
