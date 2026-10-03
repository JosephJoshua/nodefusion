(function () {
  'use strict';
  window.DiagramExplorer = {
    svg(tag, attributes = {}, text) {
      const node = document.createElementNS('http://www.w3.org/2000/svg', tag);
      for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, String(value));
      if (text !== undefined) node.textContent = text;
      return node;
    },
    timeline(host, steps, selected, change) {
      host.className = 'experiment-timeline';
      let input = host.querySelector('input');
      if (!input) {
        const label = document.createElement('label');
        label.textContent = '执行步骤';
        input = document.createElement('input');
        input.type = 'range'; input.min = '1'; input.step = '1';
        input.setAttribute('aria-label', '执行步骤');
        const output = document.createElement('output');
        const ticks = document.createElement('div'); ticks.className = 'timeline-ticks'; ticks.setAttribute('aria-hidden', 'true');
        label.append(input, output); host.append(label, ticks);
        input.addEventListener('input', () => host.change(Number(input.value) - 1));
      }
      host.change = change;
      input.max = String(steps.length); input.value = String(selected + 1);
      input.setAttribute('aria-valuetext', `第 ${selected + 1} 步，共 ${steps.length} 步：${steps[selected].title}`);
      host.querySelector('output').textContent = `${selected + 1} / ${steps.length}`;
      const ticks = host.querySelector('.timeline-ticks');
      if (ticks.childElementCount !== steps.length) {
        ticks.replaceChildren(...steps.map((_, index) => { const tick = document.createElement('span'); tick.textContent = index + 1; return tick; }));
      }
      [...ticks.children].forEach((tick, index) => tick.classList.toggle('selected', index === selected));
    },
    changes(host, pairs) {
      host.replaceChildren(...pairs.map(([label, before, after]) => {
        const row = document.createElement('li');
        row.textContent = `${label}：${before} → ${after}`; return row;
      }));
    }
  };
})();
