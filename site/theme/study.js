(function () {
  'use strict';
  const toolbar = document.querySelector('.lesson-toolbar');
  if (!toolbar) return;
  const panel = document.createElement('section');
  panel.className = 'study-panel';
  panel.hidden = true;
  panel.setAttribute('aria-label', '阅读资料');
  const header = document.createElement('div');
  header.className = 'study-header';
  const title = document.createElement('strong');
  const choices = document.createElement('select');
  choices.setAttribute('aria-label', '切换运行报告');
  const reports = new Map();
  function registerReport(href, text) {
    const url = new URL(href, location.href);
    if (url.origin !== location.origin || !/\/reports\/.*\.html$/.test(url.pathname) || reports.has(url.pathname)) return;
    const option = document.createElement('option');
    option.value = url.pathname;
    option.textContent = text;
    reports.set(url.pathname, url.href);
    choices.append(option);
  }
  for (const link of document.querySelectorAll('main a[href]')) {
    if (toolbar.contains(link)) continue;
    registerReport(link.href, link.textContent.trim());
  }
  document.querySelector('main').addEventListener('nodefusion:comparison-ready', event => {
    for (const link of event.detail.links) registerReport(link.href, event.detail.kernel + ' · ' + link.title);
    if (!panel.hidden && title.textContent === '运行报告') choices.hidden = reports.size < 2;
  });
  const status = document.createElement('span');
  status.setAttribute('role', 'status');
  const external = document.createElement('a');
  external.textContent = '新标签页 ↗';
  external.target = '_blank';
  external.rel = 'noopener';
  const expand = document.createElement('button');
  expand.type = 'button';
  expand.textContent = '展开';
  expand.setAttribute('aria-expanded', 'false');
  const dock = document.createElement('button');
  dock.type = 'button';
  dock.textContent = '左右并排';
  const wide = matchMedia('(min-width: 1200px)');
  let sideBySide = true;
  try {
    const stored = sessionStorage.getItem('nodefusion-study-side');
    if (stored !== null) sideBySide = stored === 'true';
  } catch (_) { /* Use the default layout without storage. */ }
  const close = document.createElement('button');
  close.type = 'button';
  close.textContent = '返回正文';
  const retry = document.createElement('button');
  retry.type = 'button';
  retry.textContent = '重试';
  retry.hidden = true;
  const frames = new Map();
  const filterRestorers = new Map();
  const narrow = matchMedia('(max-width: 900px), (max-height: 600px)');
  const resize = document.createElement('div');
  resize.className = 'study-resize';
  resize.tabIndex = 0;
  resize.setAttribute('role', 'separator');
  resize.setAttribute('aria-label', '调整报告高度');
  resize.setAttribute('aria-orientation', 'horizontal');
  resize.setAttribute('aria-controls', 'study-workspace');
  resize.setAttribute('aria-valuemin', '30');
  resize.setAttribute('aria-valuemax', '75');
  panel.id = 'study-workspace';
  const widthResize = document.createElement('div');
  widthResize.className = 'study-width-resize';
  widthResize.tabIndex = 0;
  widthResize.setAttribute('role', 'separator');
  widthResize.setAttribute('aria-label', '调整正文宽度');
  widthResize.setAttribute('aria-orientation', 'vertical');
  widthResize.setAttribute('aria-controls', 'study-workspace');
  widthResize.title = '拖动调整正文宽度，双击恢复默认宽度';
  let preferredWidth = 48;
  try {
    const stored = Number(sessionStorage.getItem('nodefusion-study-width'));
    if (stored >= 35 && stored <= 65) preferredWidth = stored;
  } catch (_) { /* Optional layout preference. */ }
  function widthBounds() {
    if (!wide.matches) return {min: 35, max: 65};
    return {min: Math.max(35, 550 / innerWidth * 100), max: Math.min(65, (innerWidth - 560) / innerWidth * 100)};
  }
  function setWidth(value) {
    const bounds = widthBounds();
    const actual = wide.matches ? Math.max(bounds.min, Math.min(bounds.max, value)) : value;
    document.body.style.setProperty('--study-reading-width', actual + '%');
    widthResize.setAttribute('aria-valuemin', String(Math.floor(bounds.min)));
    widthResize.setAttribute('aria-valuemax', String(Math.ceil(bounds.max)));
    widthResize.setAttribute('aria-valuenow', String(Math.round(actual)));
    widthResize.setAttribute('aria-valuetext', '正文占窗口宽度 ' + Math.round(actual) + '%');
    if (document.body.classList.contains('study-side')) panel.style.left = actual + '%';
  }
  function changeWidth(value) {
    const bounds = widthBounds();
    preferredWidth = Math.max(bounds.min, Math.min(bounds.max, value));
    preserveAnchor(() => setWidth(preferredWidth));
  }
  function saveWidth() {
    try { sessionStorage.setItem('nodefusion-study-width', String(preferredWidth)); } catch (_) { /* Optional layout preference. */ }
  }
  widthResize.addEventListener('keydown', event => {
    const bounds = widthBounds();
    const actual = parseFloat(document.body.style.getPropertyValue('--study-reading-width'));
    const values = {ArrowLeft: actual - 2, ArrowRight: actual + 2, Home: bounds.min, End: bounds.max};
    if (!(event.key in values)) return;
    event.preventDefault();
    event.stopPropagation();
    changeWidth(values[event.key]);
    saveWidth();
  });
  widthResize.addEventListener('dblclick', () => { changeWidth(48); saveWidth(); });
  let draggingWidth = false;
  widthResize.addEventListener('pointerdown', event => {
    if (event.button !== 0) return;
    draggingWidth = true;
    widthResize.setPointerCapture(event.pointerId);
    document.body.classList.add('study-resizing');
    document.body.classList.add('study-width-resizing');
  });
  widthResize.addEventListener('pointermove', event => {
    if (draggingWidth) changeWidth(event.clientX / innerWidth * 100);
  });
  function endWidthResize() {
    draggingWidth = false;
    document.body.classList.remove('study-resizing');
    document.body.classList.remove('study-width-resizing');
    saveWidth();
  }
  widthResize.addEventListener('pointerup', endWidthResize);
  widthResize.addEventListener('lostpointercapture', endWidthResize);
  let height = 56;
  try {
    const stored = Number(sessionStorage.getItem('nodefusion-study-height'));
    if (stored >= 30 && stored <= 75) height = stored;
  } catch (_) { /* Resizing also works without storage. */ }
  function setHeight(value) {
    height = Math.max(30, Math.min(75, value));
    document.body.style.setProperty('--study-height', height + 'dvh');
    resize.setAttribute('aria-valuenow', String(Math.round(height)));
    resize.setAttribute('aria-valuetext', Math.round(height) + '% 窗口高度');
  }
  function saveHeight() {
    try { sessionStorage.setItem('nodefusion-study-height', String(height)); } catch (_) { /* Optional preference. */ }
  }
  setHeight(height);
  resize.addEventListener('keydown', event => {
    const values = {ArrowUp: height + 5, ArrowDown: height - 5, Home: 30, End: 75};
    if (!(event.key in values)) return;
    event.preventDefault();
    setHeight(values[event.key]);
    saveHeight();
  });
  let dragging = false;
  resize.addEventListener('pointerdown', event => {
    if (event.button !== 0) return;
    dragging = true;
    resize.setPointerCapture(event.pointerId);
    document.body.classList.add('study-resizing');
  });
  resize.addEventListener('pointermove', event => {
    if (dragging) setHeight((innerHeight - event.clientY) / innerHeight * 100);
  });
  function endResize() {
    dragging = false;
    document.body.classList.remove('study-resizing');
    saveHeight();
  }
  resize.addEventListener('pointerup', endResize);
  resize.addEventListener('lostpointercapture', endResize);
  let opener;
  let lastReport;
  let restoringFocus = false;
  const inertBefore = new Map();
  function preserveAnchor(change) {
    const id = document.querySelector('.lesson-outline [aria-current="location"]')?.dataset.section;
    const readingTop = toolbar.getBoundingClientRect().bottom;
    const visibleHeadings = [...document.querySelectorAll('main > h2[id]')].filter(element => element.getClientRects().length);
    const heading = visibleHeadings.sort((a, b) => Math.abs(a.getBoundingClientRect().top - readingTop) - Math.abs(b.getBoundingClientRect().top - readingTop))[0] || (id && document.getElementById(id));
    const top = heading?.getBoundingClientRect().top;
    change();
    if (heading && Number.isFinite(top)) window.scrollBy(0, heading.getBoundingClientRect().top - top);
  }
  function updateLayout() {
    const fullscreen = !panel.hidden && (narrow.matches || panel.classList.contains('study-expanded'));
    const side = !panel.hidden && !fullscreen && wide.matches && sideBySide;
    if (fullscreen) {
      panel.setAttribute('role', 'dialog');
      panel.setAttribute('aria-modal', 'true');
      for (const element of document.querySelectorAll('.page-wrapper, #mdbook-sidebar, #mdbook-menu-bar')) {
        if (!inertBefore.has(element)) inertBefore.set(element, element.inert);
        element.inert = true;
      }
    } else {
      panel.setAttribute('role', 'region');
      panel.removeAttribute('aria-modal');
      for (const [element, inert] of inertBefore) element.inert = inert;
      inertBefore.clear();
    }
    expand.hidden = narrow.matches;
    dock.hidden = !wide.matches || fullscreen;
    dock.textContent = side ? '上下分屏' : '左右并排';
    resize.hidden = fullscreen || side;
    widthResize.hidden = !side;
    document.body.classList.toggle('study-fullscreen', fullscreen);
    document.body.classList.toggle('study-side', side);
    document.body.classList.toggle('study-open', !panel.hidden);
    const wrapper = document.querySelector('.page-wrapper');
    setWidth(preferredWidth);
    if (!side) panel.style.left = narrow.matches ? '0px' : Math.max(0, wrapper.getBoundingClientRect().left) + 'px';
  }
  function concealFrames() {
    for (const frame of frames.values()) {
      try {
        const playback = frame.contentDocument?.getElementById('play');
        if (playback?.textContent === '暂停') playback.click();
      } catch (_) { /* Cross-origin frames keep their native controls. */ }
      frame.hidden = true;
    }
  }
  function hide() {
    preserveAnchor(() => {
      panel.hidden = true;
      concealFrames();
      updateLayout();
    });
    const returnTarget = opener?.isConnected && opener.getClientRects().length ? opener : toolbar.querySelector('[data-study-resume]');
    if (returnTarget) {
      restoringFocus = true;
      try { returnTarget.focus({preventScroll: true}); } finally { restoringFocus = false; }
    }
  }
  function escape(event) {
    if (event.key === 'Escape' && !event.defaultPrevented && !panel.hidden) {
      event.preventDefault();
      hide();
    }
  }
  close.addEventListener('click', hide);
  retry.addEventListener('click', () => {
    const frame = [...frames.values()].find(frame => !frame.hidden);
    if (!frame) return;
    retry.hidden = true;
    status.textContent = '正在加载…';
    frame.src = external.href;
  });
  expand.addEventListener('click', () => {
    preserveAnchor(() => {
      const expanded = panel.classList.toggle('study-expanded');
      expand.textContent = expanded ? '收起' : '展开';
      expand.setAttribute('aria-expanded', String(expanded));
      updateLayout();
    });
  });
  dock.addEventListener('click', () => {
    preserveAnchor(() => {
      sideBySide = !sideBySide;
      if (sideBySide) document.querySelector('main').dispatchEvent(new CustomEvent('nodefusion:side-report'));
      updateLayout();
    });
    try { sessionStorage.setItem('nodefusion-study-side', String(sideBySide)); } catch (_) { /* Keep the current layout without storage. */ }
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && !panel.hidden && !event.defaultPrevented) {
      escape(event);
      event.stopPropagation();
    }
  }, true);
  document.addEventListener('focusin', event => {
    const target = event.target;
    if (restoringFocus || !(target instanceof HTMLElement) || !target.closest('main') || toolbar.contains(target) || target.closest('.lesson-comparison')) return;
    const top = Math.max(58, toolbar.getBoundingClientRect().bottom + 8);
    const bottom = panel.hidden || document.body.classList.contains('study-side') ? innerHeight - 8 : panel.getBoundingClientRect().top - 8;
    if (bottom <= top) return;
    const bounds = target.getBoundingClientRect();
    if (bounds.top < top || bounds.height > bottom - top) window.scrollBy(0, bounds.top - top);
    else if (bounds.bottom > bottom) window.scrollBy(0, bounds.bottom - bottom);
  });
  window.addEventListener('resize', updateLayout);
  document.getElementById('mdbook-sidebar-toggle-anchor')?.addEventListener('change', () => {
    // The book animates its directory width.
    updateLayout();
    setTimeout(updateLayout, 320);
  });
  header.append(title, choices, status, retry, external, dock, expand, close);
  panel.append(widthResize, resize, header);
  document.body.append(panel);
  function open(url, link) {
    const kind = url.pathname.includes('/reports/') ? '运行报告' : '交互图';
    const sameOpenKind = !panel.hidden && title.textContent === kind;
    if (kind === '运行报告') lastReport = url.href;
    if (kind === '运行报告' && !url.searchParams.has('tab')) url.searchParams.set('tab', 'functions');
    if (kind === '运行报告') {
      const resume = toolbar.querySelector('[data-study-resume]');
      if (resume) resume.href = url.href;
    }
    if (link) opener = link;
    title.textContent = kind;
    choices.hidden = kind !== '运行报告' || reports.size < 2;
    choices.value = url.pathname;
    external.href = url.href;
    panel.hidden = false;
    concealFrames();
    // Keep a loaded report's filters, timeline and selection when returning to it.
    const key = url.pathname;
    let frame = frames.get(key);
    if (!frame) {
      frame = document.createElement('iframe');
      frame.title = kind;
      frame.src = url.href;
      frame.addEventListener('load', () => {
        try {
          const doc = frame.contentDocument;
          if (!doc || !(frame.title === '运行报告' ? doc.querySelector('script[type="application/nodefusion"]') : doc.querySelector('#controls'))) {
            frame.dataset.failed = 'true';
            if (!frame.hidden) { status.textContent = '加载失败'; retry.hidden = false; }
            return;
          }
          frame.dataset.failed = '';
          frame.dataset.loaded = 'true';
          if (!frame.hidden) { status.textContent = ''; retry.hidden = true; }
          if (frame.title === '交互图') doc.documentElement.classList.add('embedded-diagram');
          if (frame.title === '运行报告') {
            // Older standalone reports rebuild function controls without saving their values.
            const functionPanel = doc.getElementById('panel-functions');
            if (functionPanel) {
              const controlIds = ['function-search', 'function-cpu', 'function-limit', 'function-grouping'];
              const values = new Map();
              for (const id of controlIds) {
                const control = doc.getElementById(id);
                if (control) values.set(id, control.value);
              }
              const remember = event => {
                if (controlIds.includes(event.target.id)) values.set(event.target.id, event.target.value);
              };
              doc.addEventListener('input', remember, true);
              doc.addEventListener('change', remember, true);
              const restoreFilters = () => {
                let changed;
                for (const [id, value] of values) {
                  const control = doc.getElementById(id);
                  if (!control || control.value === value) continue;
                  if (control.tagName === 'SELECT' && ![...control.options].some(option => option.value === value)) continue;
                  control.value = value;
                  changed = control;
                }
                if (changed) changed.dispatchEvent(new frame.contentWindow.Event(changed.tagName === 'INPUT' ? 'input' : 'change', {bubbles: true}));
              };
              filterRestorers.set(frame, restoreFilters);
              new frame.contentWindow.MutationObserver(restoreFilters).observe(functionPanel, {childList: true});
            }
            const revealTab = () => {
              if (!frame.contentWindow.matchMedia('(max-width: 900px)').matches) return;
              const selected = doc.querySelector('nav.tabs button.on');
              if (!selected) return;
              const tabs = selected.parentElement;
              const bounds = selected.getBoundingClientRect();
              const container = tabs.getBoundingClientRect();
              if (bounds.left < container.left) tabs.scrollLeft += bounds.left - container.left;
              else if (bounds.right > container.right) tabs.scrollLeft += bounds.right - container.right;
            };
            const stylesheet = document.querySelector('link[rel="stylesheet"][href*="education"]');
            if (stylesheet) {
              const embeddedStyles = stylesheet.cloneNode();
              embeddedStyles.href = stylesheet.href;
              embeddedStyles.addEventListener('load', revealTab);
              doc.head.append(embeddedStyles);
            }
            doc.documentElement.classList.add('embedded-study');
            const tabs = doc.querySelector('nav.tabs');
            if (tabs) {
              new frame.contentWindow.ResizeObserver(revealTab).observe(tabs);
              new frame.contentWindow.MutationObserver(revealTab).observe(tabs, {subtree: true, attributes: true, attributeFilter: ['class']});
            }
            const timebar = doc.querySelector('.timebar');
            if (timebar) {
              const information = doc.createElement('details');
              information.className = 'study-run-information';
              const summary = doc.createElement('summary');
              summary.textContent = '运行信息与时间轴';
              information.append(summary);
              timebar.before(information);
              for (const element of doc.querySelectorAll('.topbar, #capability, .minimapwrap, #deltabar')) information.append(element);
              information.open = false;
            }
          }
          doc.addEventListener('keydown', escape);
          doc.querySelector('#return-to-lesson')?.addEventListener('click', event => {
            event.preventDefault();
            hide();
          });
        } catch (_) { /* The standalone link remains available. */ }
      });
      frames.set(key, frame);
      panel.append(frame);
    }
    frame.hidden = false;
    filterRestorers.get(frame)?.();
    retry.hidden = !frame.dataset.failed;
    status.textContent = frame.dataset.failed ? '加载失败' : frame.dataset.loaded ? '' : '正在加载…';
    if (!sameOpenKind) {
      preserveAnchor(() => {
        if (sideBySide && wide.matches && !narrow.matches) document.querySelector('main').dispatchEvent(new CustomEvent('nodefusion:side-report'));
        updateLayout();
      });
    }
    if (link) close.focus({preventScroll: true});
  }
  choices.addEventListener('change', () => open(new URL(reports.get(choices.value), location.href)));
  document.querySelector('main').addEventListener('click', event => {
    const link = event.target.closest('a[href]');
    if (!link || event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    const url = new URL(link.href, location.href);
    if (url.origin !== location.origin || !/\/(reports\/.*|diagrams\/ch\d+-[a-z][a-z0-9-]*)\.html$/.test(url.pathname)) return;
    event.preventDefault();
    open(link.hasAttribute('data-study-resume') && lastReport ? new URL(lastReport) : url, link);
  });
})();
