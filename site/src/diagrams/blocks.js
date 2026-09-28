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
  const params = new URLSearchParams(location.search);
  if (layouts[params.get('kernel')]) kernel.value = params.get('kernel');
  const returnTo = params.get('return');
  if (returnTo && /^(index|rcore|ucore|exercises)\.html(?:#.*)?$/.test(returnTo)) doc.getElementById('return-to-lesson').href = '../ch6/' + returnTo;
  function render() {
    const layout = layouts[kernel.value];
    const capacity = (layout.direct + layout.entries + (layout.double ? layout.entries ** 2 : 0)) * layout.block;
    offset.max = String(capacity - 1);
    doc.getElementById('capacity').textContent = `块大小 ${layout.block} 字节；最大偏移 ${(capacity - 1).toLocaleString('en-US')}。`;
    path.replaceChildren();
    offset.setAttribute('aria-invalid', String(!offset.validity.valid || offset.value === ''));
    if (!offset.validity.valid || offset.value === '') {
      result.textContent = `输入 0 到 ${capacity - 1} 之间的整数偏移。`;
      return;
    }
    const found = locate(kernel.value, offset.valueAsNumber);
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
      node.className = 'node active';
      node.innerHTML = '<svg viewBox="0 0 220 108" preserveAspectRatio="none" aria-hidden="true"><path d="M3 4 L216 3 L217 104 L4 103 Z M5 6 L213 5 L218 101"/></svg>';
      const heading = doc.createElement('strong');
      const caption = doc.createElement('span');
      heading.textContent = title;
      caption.textContent = detail;
      node.append(heading, caption);
      path.append(node);
    }
    const layer = ['直接地址', '一级间接索引', '二级间接索引'][found.level];
    result.textContent = `偏移 ${offset.valueAsNumber.toLocaleString('en-US')} ÷ ${found.blockSize} = 逻辑块 ${found.logical}，余数 ${found.within}。使用${layer}，读取数据块内的第 ${found.within} 字节。`;
  }
  function makeBoundaries() {
    const layout = layouts[kernel.value];
    const values = [['直接索引末尾', layout.direct * layout.block - 1], ['一级间接起点', layout.direct * layout.block]];
    if (layout.double) values.push(['二级间接起点', (layout.direct + layout.entries) * layout.block]);
    boundaries.replaceChildren(...values.map(([label, value]) => {
      const button = doc.createElement('button');
      button.type = 'button';
      button.textContent = label;
      button.addEventListener('click', () => { offset.value = value; render(); });
      return button;
    }));
  }
  kernel.addEventListener('change', () => { makeBoundaries(); render(); });
  offset.addEventListener('input', render);
  makeBoundaries();
  render();
  doc.getElementById('controls').hidden = false;
  doc.getElementById('static-diagram').open = false;
})(typeof window === 'undefined' ? globalThis : window);
