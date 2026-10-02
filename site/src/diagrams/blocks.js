(function (root) {
  'use strict';
  const layouts = {
    rcore: {block: 512, direct: 27, entries: 128, double: true},
    ucore: {block: 1024, direct: 12, entries: 256, double: false}
  };
  function locate(kernel, offset) {
    const layout = layouts[kernel];
    if (!layout) throw new RangeError('Unknown layout');
    const blocks = layout.direct + layout.entries + (layout.double ? layout.entries ** 2 : 0);
    if (!Number.isSafeInteger(offset) || offset < 0 || offset >= blocks * layout.block) throw new RangeError('Offset outside file capacity');
    const logical = Math.floor(offset / layout.block);
    const result = {logical, within: offset % layout.block, capacity: blocks * layout.block, blockSize: layout.block};
    if (logical < layout.direct) return {...result, level: 0, indices: [logical]};
    if (logical < layout.direct + layout.entries) return {...result, level: 1, indices: [logical - layout.direct]};
    const index = logical - layout.direct - layout.entries;
    return {...result, level: 2, indices: [Math.floor(index / layout.entries), index % layout.entries]};
  }
  if (typeof module !== 'undefined' && module.exports) module.exports = {locate, layouts};
  if (!root.document) return;
  const doc = root.document;
  const kernel = doc.getElementById('kernel');
  const offset = doc.getElementById('offset');
  const path = doc.getElementById('block-path');
  const result = doc.getElementById('result');
  const boundaries = doc.getElementById('boundaries');
  const scope = doc.getElementById('offset-scope');
  function intervalsFor(layout) {
    const intervals = [[0, layout.direct * layout.block], [layout.direct * layout.block, (layout.direct + layout.entries) * layout.block]];
    if (layout.double) intervals.push([intervals[1][1], (layout.direct + layout.entries + layout.entries ** 2) * layout.block]);
    return intervals;
  }
  const params = new URLSearchParams(location.search);
  if (layouts[params.get('kernel')]) kernel.value = params.get('kernel');
  const returnTo = params.get('return');
  if (returnTo && /^(index|rcore|ucore)\.html(?:#.*)?$/.test(returnTo)) doc.getElementById('return-to-lesson').href = '../ch6/' + returnTo;
  function render() {
    const layout = layouts[kernel.value];
    const capacity = (layout.direct + layout.entries + (layout.double ? layout.entries ** 2 : 0)) * layout.block;
    offset.max = String(capacity - 1);
    const slider = doc.getElementById('offset-slider'); slider.max = offset.max;
    doc.getElementById('capacity').textContent = `块大小 ${layout.block} 字节；最大偏移 ${(capacity - 1).toLocaleString('en-US')}。`;
    path.replaceChildren();
    offset.setAttribute('aria-invalid', String(!offset.validity.valid || offset.value === ''));
    if (!offset.validity.valid || offset.value === '') {
      slider.disabled = true;
      doc.getElementById('offset-value').textContent = '等待有效偏移';
      for (const band of doc.querySelectorAll('.index-band')) band.setAttribute('aria-pressed', 'false');
      result.textContent = `输入 0 到 ${capacity - 1} 之间的整数偏移。`;
      doc.getElementById('byte-offset-label').textContent = '等待有效偏移';
      doc.getElementById('byte-marker').hidden = true;
      doc.getElementById('lookup-cost').textContent = '';
      doc.getElementById('lookup-insight').textContent = '';
      doc.getElementById('address-equation').replaceChildren();
      doc.getElementById('previous-block').disabled = true;
      doc.getElementById('next-block').disabled = true;
      return;
    }
    const found = locate(kernel.value, offset.valueAsNumber);
    slider.disabled = false;
    const intervals = intervalsFor(layout);
    if (scope.value !== 'all' && !intervals[Number(scope.value)]) scope.value = String(found.level);
    if (scope.value !== 'all' && (offset.valueAsNumber < intervals[Number(scope.value)][0] || offset.valueAsNumber >= intervals[Number(scope.value)][1])) scope.value = String(found.level);
    const [start, end] = scope.value === 'all' ? [0, capacity] : intervals[Number(scope.value)];
    slider.min = start; slider.max = end - 1;
    doc.getElementById('previous-block').disabled = found.logical === 0;
    doc.getElementById('next-block').disabled = (found.logical + 1) * layout.block >= capacity;
    const equation = doc.getElementById('address-equation'); equation.replaceChildren();
    for (const [value, label] of [[offset.valueAsNumber, '字节偏移'], ['=', ''], [found.logical, '逻辑块号'], ['×', ''], [found.blockSize, '块大小'], ['+', ''], [found.within, '块内偏移']]) {
      const term = doc.createElement('span'), number = doc.createElement('strong'), caption = doc.createElement('span');
      number.textContent = value; caption.textContent = label; term.append(number, caption); equation.append(term);
    }
    slider.value = offset.value;
    doc.getElementById('offset-value').textContent = `${start.toLocaleString('en-US')}–${(end - 1).toLocaleString('en-US')} 字节 · 当前 ${offset.valueAsNumber.toLocaleString('en-US')}`;
    for (const band of doc.querySelectorAll('.index-band')) band.setAttribute('aria-pressed', String(Number(band.dataset.level) === found.level));
    const marker = doc.getElementById('byte-marker'); marker.hidden = false;
    marker.style.left = `${found.within / found.blockSize * 100}%`;
    doc.getElementById('byte-offset-label').textContent = `块内偏移 ${found.within} / ${found.blockSize - 1}`;
    doc.getElementById('lookup-cost').textContent = `查找路径：${found.level} 个索引块 + 1 个数据块`;
    doc.getElementById('lookup-insight').textContent = found.level === 0
      ? '数据块地址直接保存在 inode 中。跨过直接索引末尾后，需要从索引块读取地址。'
      : found.level === 1
        ? `一级索引块存放 ${layout.entries} 个地址。该区间覆盖 ${layout.entries * layout.block} 字节；跨块时块内偏移从 0 重新开始。索引块已缓存时可直接使用缓存内容。`
        : `二级索引先选择一级索引块，再选择其中的数据块地址。两个下标分别为 ${found.indices[0]} 和 ${found.indices[1]}；这层索引覆盖 ${layout.entries ** 2 * layout.block} 字节。索引层数表示查找结构，不等于实际磁盘 I/O 次数。`;
    const nodes = found.level === 0 ? [['inode', `直接地址 [${found.indices[0]}]`]] : found.level === 1 ?
      [['inode', '一级间接地址'], ['一级间接块', `地址项 [${found.indices[0]}]`]] :
      [['inode', '二级间接地址'], ['二级间接块', `地址项 [${found.indices[0]}]`], ['一级间接块', `地址项 [${found.indices[1]}]`]];
    nodes.push(['数据块', `文件逻辑块 ${found.logical}`]);
    for (const [i, [title, detail]] of nodes.entries()) {
      if (i) {
        const arrow = doc.createElement('span');
        arrow.className = 'edge active';
        arrow.textContent = '→';
        arrow.setAttribute('aria-hidden', 'true');
        path.append(arrow);
      }
      const node = doc.createElement('div');
      node.className = 'node active index-block';
      const heading = doc.createElement('strong');
      const caption = doc.createElement('span');
      heading.textContent = title;
      caption.textContent = detail;
      if (title.includes('间接块')) caption.textContent = `${layout.entries} 个地址项`;
      if (title === 'inode' && found.level === 0) caption.textContent = `${layout.direct} 个直接地址`;
      node.append(heading, caption);
      if (title === '数据块') {
        const bytes = doc.createElement('div'); bytes.className = 'byte-window';
        const start = Math.floor(found.within / 8) * 8;
        for (let byte = start; byte < Math.min(start + 8, layout.block); byte++) {
          const button = doc.createElement('button'); button.type = 'button'; button.textContent = byte;
          button.setAttribute('aria-label', `块内第 ${byte} 字节`); button.setAttribute('aria-pressed', String(byte === found.within));
          button.onclick = () => { offset.value = found.logical * layout.block + byte; render(); path.querySelector('.byte-window [aria-pressed=true]')?.focus({preventScroll: true}); }; bytes.append(button);
        }
        node.append(bytes);
      } else {
        const selected = title === 'inode' ? (found.level === 0 ? found.indices[0] : null) : title === '二级间接块' ? found.indices[0] : found.indices.at(-1);
        if (selected !== null) {
          const count = title === 'inode' ? layout.direct : layout.entries;
          const slots = doc.createElement('div'); slots.className = 'index-slots';
          const choices = [...new Set([0, Math.max(0, selected - 1), selected, Math.min(count - 1, selected + 1), count - 1])].sort((a, b) => a - b);
          let last = -1;
          for (const slot of choices) {
            if (slot > last + 1) { const gap = doc.createElement('span'); gap.className = 'slot-gap'; gap.textContent = '⋮'; slots.append(gap); }
            const button = doc.createElement('button'); button.type = 'button'; button.textContent = slot === selected ? `地址项 [${slot}]` : `[${slot}]`;
            button.setAttribute('aria-label', `${title}地址项 [${slot}]`);
            button.setAttribute('aria-pressed', String(slot === selected));
            button.onclick = () => {
              const logical = title === 'inode' ? slot : found.level === 1 ? layout.direct + slot : layout.direct + layout.entries +
                (title === '二级间接块' ? slot * layout.entries + found.indices[1] : found.indices[0] * layout.entries + slot);
              offset.value = logical * layout.block + found.within; render();
              [...path.querySelectorAll('.index-block')].find(block => block.querySelector('strong').textContent === title)?.querySelector('[aria-pressed=true]')?.focus({preventScroll: true});
            };
            slots.append(button); last = slot;
          }
          node.append(slots);
        } else {
          const pointer = doc.createElement('div'); pointer.className = 'inode-pointer'; pointer.textContent = kernel.value === 'ucore' ? 'addrs[12]' : found.level === 1 ? 'indirect1' : 'indirect2'; node.append(pointer);
        }
      }
      path.append(node);
    }
    const layer = ['直接地址', '一级间接索引', '二级间接索引'][found.level];
    result.textContent = `逻辑块 ${found.logical} · 余数 ${found.within} · ${layer}`;
  }
  function makeBoundaries() {
    const layout = layouts[kernel.value];
    scope.querySelector('option[value="2"]').disabled = !layout.double;
    const values = [['直接索引末尾', layout.direct * layout.block - 1], ['一级间接起点', layout.direct * layout.block]];
    if (layout.double) values.push(['二级间接起点', (layout.direct + layout.entries) * layout.block]);
    boundaries.replaceChildren(...values.map(([label, value]) => {
      const button = doc.createElement('button');
      button.type = 'button';
      button.textContent = label;
      button.addEventListener('click', () => { offset.value = value; render(); });
      return button;
    }));
    const intervals = [[0, layout.direct * layout.block, '直接索引'], [layout.direct * layout.block, (layout.direct + layout.entries) * layout.block, '一级间接索引']];
    if (layout.double) intervals.push([intervals[1][1], (layout.direct + layout.entries + layout.entries ** 2) * layout.block, '二级间接索引']);
    const bands = doc.getElementById('index-bands'); bands.style.gridTemplateColumns = `repeat(${intervals.length}, minmax(0, 1fr))`;
    bands.replaceChildren(...intervals.map(([start, end, label], level) => {
      const button = doc.createElement('button'); button.type = 'button'; button.className = 'index-band'; button.dataset.level = String(level);
      button.textContent = label;
      const range = doc.createElement('span'); range.textContent = `${start.toLocaleString('en-US')}–${(end - 1).toLocaleString('en-US')} B`; button.append(range);
      button.onclick = () => { offset.value = start; render(); }; return button;
    }));
  }
  kernel.addEventListener('change', () => { makeBoundaries(); render(); });
  offset.addEventListener('input', render);
  scope.addEventListener('change', () => {
    if (scope.value === 'all' && (!offset.validity.valid || offset.value === '')) offset.value = 0;
    if (scope.value !== 'all') {
      const [start, end] = intervalsFor(layouts[kernel.value])[Number(scope.value)];
      if (!offset.validity.valid || offset.valueAsNumber < start || offset.valueAsNumber >= end) offset.value = start;
    }
    render();
  });
  for (const [id, direction] of [['previous-block', -1], ['next-block', 1]]) doc.getElementById(id).addEventListener('click', () => {
    offset.value = offset.valueAsNumber + direction * layouts[kernel.value].block; render();
  });
  doc.getElementById('offset-slider').addEventListener('input', event => { offset.value = event.target.value; render(); });
  makeBoundaries();
  render();
  doc.getElementById('controls').hidden = false;
  doc.getElementById('static-diagram').open = false;
})(typeof window === 'undefined' ? globalThis : window);
