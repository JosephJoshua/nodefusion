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
      host.setAttribute('aria-label', '选择执行步骤');
      host.replaceChildren(...steps.map((step, index) => {
        const button = document.createElement('button');
        button.type = 'button'; button.textContent = String(index + 1);
        const caption = document.createElement('span'); caption.textContent = step.title; button.append(caption);
        button.title = step.title; button.setAttribute('aria-label', `${index + 1}：${step.title}`);
        if (index === selected) button.setAttribute('aria-current', 'step');
        if (index < selected) button.className = 'completed';
        button.addEventListener('click', () => { change(index); host.querySelector('[aria-current]')?.focus({preventScroll: true}); });
        return button;
      }));
      const selectedButton = host.querySelector('[aria-current]');
      if (selectedButton) {
        const left = selectedButton.getBoundingClientRect().left - host.getBoundingClientRect().left + host.scrollLeft;
        if (left < host.scrollLeft) host.scrollLeft = left;
        else if (left + selectedButton.offsetWidth > host.scrollLeft + host.clientWidth) host.scrollLeft = left + selectedButton.offsetWidth - host.clientWidth;
      }
    },
    changes(host, pairs) {
      host.replaceChildren(...pairs.map(([label, before, after]) => {
        const row = document.createElement('li');
        row.textContent = `${label}：${before} → ${after}`; return row;
      }));
    },
    queue(host, title, value) {
      host.replaceChildren();
      const label = document.createElement('span'); label.textContent = title; host.append(label);
      const names = value.match(/[ABC]/g) || [];
      for (const name of names) {
        const token = document.createElement('span'); token.className = 'queue-token'; token.textContent = name; host.append(token);
      }
      if (!names.length) host.append(document.createTextNode('空'));
    }
  };
})();
