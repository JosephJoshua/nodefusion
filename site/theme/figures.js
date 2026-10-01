(function () {
  'use strict';
  const images = [...document.querySelectorAll('main img[src*="diagrams/"][src$=".svg"]')];
  if (!images.length || !window.HTMLDialogElement) return;
  const names = {
    'ch1-boot.svg': '启动过程与内存布局',
    'ch2-batch.svg': '批处理与系统调用',
    'ch3-context.svg': '用户上下文与任务上下文',
    'ch3-switch.svg': '任务切换路径',
    'ch4-sv39.svg': 'Sv39 地址转换',
    'ch5-lifecycle.svg': '进程退出与资源回收',
    'ch6-blocks.svg': '文件偏移与块索引',
    'ch6-files.svg': '文件对象与引用关系',
    'ch7-pipe.svg': '管道的环形缓冲区',
    'ch8-sync.svg': '锁与条件变量',
    'ch8-threads.svg': '进程与线程'
  };
  const nameOf = source => names[new URL(source.src).pathname.split('/').pop()] || source.alt;
  const dialog = document.createElement('dialog');
  dialog.className = 'figure-viewer';
  dialog.setAttribute('aria-label', '查看配图');
  const toolbar = document.createElement('div');
  toolbar.className = 'figure-viewer-toolbar';
  const title = document.createElement('strong');
  const viewport = document.createElement('div');
  viewport.className = 'figure-viewport';
  viewport.tabIndex = 0;
  viewport.setAttribute('aria-label', '配图，可滚动查看');
  const image = document.createElement('img');
  viewport.append(image);
  let scale = 1;
  let fitScale = 1;
  let dimensions = {width: 880, height: 480};
  let opener;
  function button(label, action) {
    const control = document.createElement('button');
    control.type = 'button';
    control.textContent = label;
    control.addEventListener('click', action);
    toolbar.append(control);
    return control;
  }
  function zoom(value) {
    const old = scale;
    const centerX = (viewport.scrollLeft + viewport.clientWidth / 2) / old;
    const centerY = (viewport.scrollTop + viewport.clientHeight / 2) / old;
    scale = Math.max(fitScale, Math.min(3, value));
    image.style.width = dimensions.width * scale + 'px';
    image.style.height = dimensions.height * scale + 'px';
    viewport.scrollLeft = centerX * scale - viewport.clientWidth / 2;
    viewport.scrollTop = centerY * scale - viewport.clientHeight / 2;
    percentage.textContent = Math.round(scale * 100) + '%';
    smaller.disabled = scale <= fitScale;
    larger.disabled = scale >= 3;
  }
  toolbar.append(title);
  const smaller = button('缩小', () => zoom(scale / 1.25));
  const percentage = document.createElement('output');
  percentage.setAttribute('aria-label', '缩放比例');
  percentage.setAttribute('aria-live', 'polite');
  toolbar.append(percentage);
  const larger = button('放大', () => zoom(scale * 1.25));
  button('适应窗口', () => zoom(fitScale));
  button('100%', () => zoom(1));
  button('关闭', () => dialog.close());
  dialog.append(toolbar, viewport);
  document.body.append(dialog);
  function fit() {
    fitScale = Math.min(1, (viewport.clientWidth - 24) / dimensions.width,
      (viewport.clientHeight - 24) / dimensions.height);
    zoom(fitScale);
  }
  function open(source, trigger) {
    opener = trigger;
    title.textContent = nameOf(source);
    image.alt = source.alt;
    image.onload = () => {
      dimensions = {width: image.naturalWidth || 880, height: image.naturalHeight || 480};
      fit();
    };
    dialog.showModal();
    image.src = source.src;
    if (image.complete && image.naturalWidth) image.onload();
  }
  dialog.addEventListener('close', () => opener?.focus({preventScroll: true}));
  dialog.addEventListener('click', event => { if (event.target === dialog) dialog.close(); });
  dialog.addEventListener('keydown', event => {
    if (event.key === 'Escape') event.stopPropagation();
    if (event.key === '+' || event.key === '=') { event.preventDefault(); zoom(scale * 1.25); }
    if (event.key === '-') { event.preventDefault(); zoom(scale / 1.25); }
  });
  window.addEventListener('resize', () => { if (dialog.open) fit(); });
  for (const source of images) {
    let link = source.closest('a');
    if (!link) {
      link = document.createElement('a');
      link.href = source.src;
      source.replaceWith(link);
      link.append(source);
    }
    link.classList.add('figure-link');
    link.setAttribute('aria-label', '放大配图：' + nameOf(source));
    link.addEventListener('click', event => {
      if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
      event.preventDefault();
      open(source, link);
    });
    const label = document.createElement('span');
    label.className = 'figure-zoom-label';
    label.textContent = '放大图';
    label.setAttribute('aria-hidden', 'true');
    link.append(label);
  }
})();
