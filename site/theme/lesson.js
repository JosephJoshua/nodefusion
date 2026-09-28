(function () {
  'use strict';
  const name = location.pathname.split('/').pop();
  const chapter = location.pathname.match(/\/ch([1-8])\//)?.[1];
  if (!chapter || name === 'print.html') return;
  const main = document.querySelector('main');
  if (!main) return;
  const toolbar = document.createElement('nav');
  toolbar.className = 'lesson-toolbar';
  toolbar.setAttribute('aria-label', '第' + '一二三四五六七八'[Number(chapter) - 1] + '章阅读导航');
  const links = document.createElement('div');
  links.className = 'lesson-links';
  let diagramLink;
  const pages = [['导读', 'index.html'], ['rCore', 'rcore.html'], ['uCore', 'ucore.html'], ['比较与练习', 'exercises.html']];
  const implementation = ['rcore.html', 'ucore.html'].includes(name);
  const counterpart = name === 'rcore.html' ? 'ucore' : 'rcore';
  const sectionPairs = chapter !== '3' ? [] : [
    ['任务数组与静态资源', '进程表与上下文'],
    ['首次运行', '调度器选择进程'],
    ['让出与选择下一个任务', '让出处理器'],
    ['切换后从哪里继续', '让出处理器'],
    ['时钟抢占与退出', '退出与批次结束']
  ];
  function matchingSection(id) {
    if (chapter === '2' && name === 'ucore.html' && id === '栈地址与上下文页') return '异常入口与上下文';
    const pair = sectionPairs.find(pair => pair[name === 'rcore.html' ? 0 : 1] === id);
    return pair ? pair[name === 'rcore.html' ? 1 : 0] : id;
  }
  let counterpartLink;
  const diagramPage = chapter === '3' ? 'ch3-switch.html' : chapter === '6' ? 'ch6-blocks.html' : chapter === '7' ? 'ch7-pipe.html' : chapter === '8' ? 'ch8-sync.html' : null;
  if (diagramPage) pages.push(['交互图', '../diagrams/' + diagramPage]);
  for (const [title, path] of pages) {
    const a = document.createElement('a');
    a.textContent = title;
    a.href = path;
    if (title === '交互图') diagramLink = a;
    if (path === name) a.setAttribute('aria-current', 'page');
    if (implementation && path === counterpart + '.html') counterpartLink = a;
    links.append(a);
  }
  const label = document.createElement('label');
  label.textContent = '小节';
  const select = document.createElement('select');
  select.setAttribute('aria-label', '跳转到小节');
  const headings = [...main.querySelectorAll('h2[id]')];
  const outline = document.createElement('aside');
  outline.className = 'lesson-outline';
  const outlineNav = document.createElement('nav');
  outlineNav.setAttribute('aria-label', '本页小节');
  const outlineTitle = document.createElement('p');
  outlineTitle.textContent = '本页小节';
  const outlineList = document.createElement('ol');
  outlineNav.append(outlineTitle, outlineList);
  outline.append(outlineNav);
  const outlineLinks = [];
  const readingHistory = [];
  let currentSection = '';
  let sectionMode = true;
  try {
    const stored = sessionStorage.getItem('nodefusion-section-reading');
    if (stored !== null) sectionMode = stored === 'true';
  } catch (_) { /* Use section reading without storage. */ }
  const sectionNodes = new Map();
  const introduction = [];
  let group;
  for (const node of [...main.children]) {
    node.dataset.lessonContent = '';
    if (headings.includes(node)) {
      group = [];
      sectionNodes.set(node.id, group);
    }
    if (group) group.push(node);
    else if (node.tagName !== 'H1') introduction.push(node);
  }
  const mode = document.createElement('button');
  mode.type = 'button';
  mode.className = 'lesson-mode';
  mode.textContent = '逐节阅读';
  mode.title = '开启时只显示当前小节，关闭后连续阅读全章';
  mode.setAttribute('aria-pressed', String(sectionMode));
  const footer = document.createElement('nav');
  footer.className = 'lesson-paging';
  footer.setAttribute('aria-label', '小节前后导航');
  const footerPrevious = document.createElement('button');
  const footerNext = document.createElement('button');
  const position = document.createElement('output');
  position.setAttribute('aria-label', '小节位置');
  const toolbarPosition = document.createElement('output');
  toolbarPosition.className = 'lesson-position';
  toolbarPosition.setAttribute('aria-label', '当前小节位置');
  for (const [button, direction] of [[footerPrevious, -1], [footerNext, 1]]) {
    button.type = 'button';
    button.addEventListener('click', () => {
      const target = headings[select.selectedIndex + direction];
      if (target) goToSection(target.id, true);
    });
  }
  footer.append(footerPrevious, position, footerNext);
  function displaySection() {
    for (const [id, nodes] of sectionNodes) {
      for (const node of nodes) node.hidden = sectionMode && id !== select.value;
    }
    for (const node of introduction) node.hidden = sectionMode && select.selectedIndex !== 0;
    main.classList.toggle('section-reading', sectionMode);
    mode.setAttribute('aria-pressed', String(sectionMode));
    footer.hidden = !sectionMode;
    const index = select.selectedIndex;
    footerPrevious.disabled = index <= 0;
    footerNext.disabled = index >= headings.length - 1;
    footerPrevious.textContent = index > 0 ? '↑ ' + headings[index - 1].textContent : '已到第一节';
    footerNext.textContent = index < headings.length - 1 ? headings[index + 1].textContent + ' ↓' : '已到最后一节';
    position.textContent = `${index + 1} / ${headings.length}`;
    toolbarPosition.textContent = position.textContent;
  }
  mode.addEventListener('click', () => {
    preserveReadingPosition(() => {
      sectionMode = !sectionMode;
      displaySection();
    });
    history.replaceState(null, '', '#' + encodeURIComponent(select.value));
    try { sessionStorage.setItem('nodefusion-section-reading', String(sectionMode)); } catch (_) { /* Keep the current mode without storage. */ }
  });
  const back = document.createElement('button');
  back.type = 'button';
  back.className = 'lesson-back';
  back.textContent = '返回';
  back.setAttribute('aria-label', '返回跳转前的位置');
  back.disabled = true;
  back.addEventListener('click', () => {
    const point = readingHistory.pop();
    if (!point) return;
    select.value = point.section;
    sectionMode = point.sectionMode;
    displaySection();
    try { sessionStorage.setItem('nodefusion-section-reading', String(sectionMode)); } catch (_) { /* Optional reading preference. */ }
    history.replaceState(null, '', point.hash || location.pathname + location.search);
    window.scrollTo(0, point.y);
    back.disabled = readingHistory.length === 0;
    updateCurrentSection();
  });
  function goToSection(id, focusHeading = false) {
    const heading = document.getElementById(id);
    if (!heading) return;
    if (id !== currentSection) {
      readingHistory.push({section: currentSection, y: window.scrollY, hash: location.hash, sectionMode});
      if (readingHistory.length > 20) readingHistory.shift();
      back.disabled = false;
    }
    select.value = id;
    displaySection();
    history.replaceState(null, '', '#' + id);
    measure();
    heading.scrollIntoView({block: 'start'});
    updateCurrentSection();
    if (focusHeading) {
      heading.tabIndex = -1;
      heading.focus({preventScroll: true});
    }
  }
  const previous = document.createElement('button');
  const next = document.createElement('button');
  for (const [button, text, title, direction] of [[previous, '↑', '上一节', -1], [next, '↓', '下一节', 1]]) {
    button.type = 'button';
    button.textContent = text;
    button.title = title;
    button.setAttribute('aria-label', title);
    button.addEventListener('click', () => {
      const target = headings[select.selectedIndex + direction];
      if (target) goToSection(target.id);
    });
  }
  function updateCurrentSection() {
    currentSection = select.value;
    toolbarPosition.textContent = `${select.selectedIndex + 1} / ${headings.length}`;
    previous.disabled = select.selectedIndex <= 0;
    next.disabled = select.selectedIndex < 0 || select.selectedIndex >= headings.length - 1;
    for (const link of outlineLinks) {
      if (link.dataset.section === select.value) link.setAttribute('aria-current', 'location');
      else link.removeAttribute('aria-current');
    }
    updateDiagramLink();
    if (counterpartLink) counterpartLink.href = counterpart + '.html#' + encodeURIComponent(matchingSection(select.value));
    updateComparison();
  }
  function updateDiagramLink() {
    if (!diagramLink) return;
    const params = new URLSearchParams();
    if (name === 'rcore.html' || name === 'ucore.html') params.set('kernel', name.split('.')[0]);
    params.set('return', name + (select.value ? '#' + select.value : ''));
    diagramLink.href = '../diagrams/' + diagramPage + '?' + params;
  }
  for (const h of headings) {
    const option = document.createElement('option');
    option.value = h.id;
    option.textContent = h.textContent;
    select.append(option);
    const item = document.createElement('li');
    const link = document.createElement('a');
    link.href = '#' + encodeURIComponent(h.id);
    link.dataset.section = h.id;
    link.textContent = h.textContent;
    link.addEventListener('click', event => {
      event.preventDefault();
      goToSection(h.id);
    });
    item.append(link);
    outlineList.append(item);
    outlineLinks.push(link);
  }
  select.addEventListener('change', () => {
    goToSection(select.value);
  });
  label.append(select);
  const sectionRow = document.createElement('div');
  sectionRow.className = 'lesson-section';
  sectionRow.append(label, previous, next);
  links.append(toolbarPosition, mode, back);
  let comparison;
  let comparisonBody;
  let comparisonSelect;
  let follow;
  let comparisonToggle;
  let comparisonDocument;
  let pendingComparison;
  let lastComparisonSection;
  const wide = window.matchMedia('(min-width: 1200px)');
  function preserveReadingPosition(change) {
    const heading = document.getElementById(select.value);
    const top = heading?.getBoundingClientRect().top;
    change();
    if (heading && Number.isFinite(top)) window.scrollBy(0, heading.getBoundingClientRect().top - top);
  }
  function renderComparison(id) {
    if (!comparisonDocument) return;
    const heading = comparisonDocument.getElementById(id);
    if (!heading) return;
    const nodes = [heading.cloneNode(true)];
    for (let node = heading.nextElementSibling; node && node.tagName !== 'H2'; node = node.nextElementSibling) {
      nodes.push(node.cloneNode(true));
    }
    comparisonBody.replaceChildren(...nodes);
    // Cloned content must not duplicate the reading page's fragment targets.
    for (const element of comparisonBody.querySelectorAll('[id]')) element.removeAttribute('id');
    for (const link of comparisonBody.querySelectorAll('a[href]')) {
      link.href = new URL(link.getAttribute('href'), new URL(counterpart + '.html', location.href)).href;
      if (/\/reports\/.*\.html$/.test(new URL(link.href).pathname)) link.removeAttribute('target');
      else link.target = '_blank';
      link.rel = 'noopener';
    }
    comparisonSelect.value = id;
    comparisonBody.scrollTop = 0;
  }
  function updateComparison() {
    if (!comparisonDocument || !comparison || comparison.hidden || !follow.checked) return;
    if (lastComparisonSection === select.value) return;
    lastComparisonSection = select.value;
    const id = matchingSection(select.value);
    if (comparisonDocument.getElementById(id)) renderComparison(id);
  }
  function closeComparison(returnFocus) {
    if (!comparison) return;
    preserveReadingPosition(() => {
      comparison.hidden = true;
      main.classList.remove('comparison-open');
    });
    comparisonToggle.setAttribute('aria-expanded', 'false');
    if (returnFocus) comparisonToggle.focus();
  }
  main.addEventListener('nodefusion:side-report', () => closeComparison(false));
  async function loadComparison() {
    if (comparisonDocument) return;
    if (pendingComparison) return pendingComparison;
    comparisonBody.textContent = '正在加载…';
    comparison.setAttribute('aria-busy', 'true');
    pendingComparison = (async () => {
      try {
        const response = await fetch(counterpart + '.html');
        if (!response.ok) throw new Error('Unable to load chapter');
        const parsed = new DOMParser().parseFromString(await response.text(), 'text/html');
        const otherHeadings = [...parsed.querySelectorAll('main h2[id]')];
        if (!otherHeadings.length) throw new Error('Chapter has no sections');
        comparisonDocument = parsed;
        main.dispatchEvent(new CustomEvent('nodefusion:comparison-ready', {detail: {
          links: [...parsed.querySelectorAll('main a[href]')].map(link => ({
            href: new URL(link.getAttribute('href'), new URL(counterpart + '.html', location.href)).href,
            title: link.textContent.trim()
          })),
          kernel: counterpart === 'ucore' ? 'uCore' : 'rCore'
        }}));
        comparisonSelect.replaceChildren(...otherHeadings.map(heading => {
          const option = document.createElement('option');
          option.value = heading.id;
          option.textContent = heading.textContent;
          return option;
        }));
        comparisonSelect.disabled = false;
        renderComparison(comparisonDocument.getElementById(matchingSection(select.value)) ? matchingSection(select.value) : otherHeadings[0].id);
        lastComparisonSection = select.value;
      } catch (_) {
        comparisonBody.textContent = '对照内容加载失败。';
        const retry = document.createElement('button');
        retry.type = 'button';
        retry.textContent = '重试';
        retry.addEventListener('click', loadComparison);
        comparisonBody.append(retry);
      } finally {
        comparison.removeAttribute('aria-busy');
        pendingComparison = null;
      }
    })();
    return pendingComparison;
  }
  if (implementation) {
    comparisonToggle = document.createElement('button');
    comparisonToggle.className = 'comparison-toggle';
    comparisonToggle.type = 'button';
    comparisonToggle.textContent = '对照阅读';
    comparisonToggle.setAttribute('aria-expanded', 'false');
    comparisonToggle.setAttribute('aria-controls', 'lesson-comparison');
    links.append(comparisonToggle);
    comparison = document.createElement('aside');
    comparison.id = 'lesson-comparison';
    comparison.className = 'lesson-comparison';
    comparison.hidden = true;
    comparison.setAttribute('aria-label', counterpart === 'ucore' ? 'uCore 对照阅读' : 'rCore 对照阅读');
    const panel = document.createElement('div');
    panel.className = 'comparison-panel';
    const header = document.createElement('div');
    header.className = 'comparison-header';
    const title = document.createElement('strong');
    title.textContent = counterpart === 'ucore' ? 'uCore 实现' : 'rCore 实现';
    const close = document.createElement('button');
    close.type = 'button';
    close.textContent = '关闭';
    close.setAttribute('aria-label', '关闭对照阅读');
    close.addEventListener('click', () => closeComparison(true));
    header.append(title, close);
    const choices = document.createElement('label');
    choices.textContent = '小节';
    comparisonSelect = document.createElement('select');
    comparisonSelect.setAttribute('aria-label', '对照小节');
    comparisonSelect.disabled = true;
    comparisonSelect.addEventListener('change', () => {
      follow.checked = false;
      renderComparison(comparisonSelect.value);
    });
    choices.append(comparisonSelect);
    const followLabel = document.createElement('label');
    followLabel.className = 'comparison-follow';
    follow = document.createElement('input');
    follow.type = 'checkbox';
    follow.checked = true;
    follow.addEventListener('change', () => { lastComparisonSection = null; updateComparison(); });
    followLabel.append(follow, '跟随正文');
    comparisonBody = document.createElement('div');
    comparisonBody.className = 'comparison-body';
    comparisonBody.tabIndex = 0;
    comparisonBody.setAttribute('aria-label', '对照正文');
    panel.append(header, choices, followLabel, comparisonBody);
    comparison.append(panel);
    comparisonToggle.addEventListener('click', () => {
      if (!comparison.hidden) return closeComparison(false);
      preserveReadingPosition(() => {
        comparison.hidden = false;
        main.classList.add('comparison-open');
      });
      comparisonToggle.setAttribute('aria-expanded', 'true');
      lastComparisonSection = null;
      loadComparison().then(updateComparison);
    });
    document.addEventListener('keydown', event => {
      if (event.key === 'Escape' && !event.defaultPrevented && !comparison.hidden && !document.querySelector('.study-panel:not([hidden])')) {
        closeComparison(true);
        event.preventDefault();
        event.stopPropagation();
      }
    }, true);
    wide.addEventListener('change', () => {
      if (wide.matches) return;
      const hadFocus = comparison.contains(document.activeElement);
      closeComparison(false);
      if (hadFocus) counterpartLink.focus();
    });
  }
  if (name === 'rcore.html' || name === 'ucore.html') {
    const report = document.createElement('a');
    const kernel = name.split('.')[0];
    const folder = kernel === 'ucore' ? 'ucoreos' : kernel;
    const recordedReport = [...main.querySelectorAll('a[href]')].find(link =>
      link.getAttribute('href').startsWith(`../reports/${folder}/ch${chapter}/2026a/`) &&
      link.getAttribute('href').endsWith('.html'));
    if (recordedReport) report.href = recordedReport.href;
    report.textContent = '运行报告';
    report.dataset.studyResume = '';
    report.target = '_blank';
    report.rel = 'noopener';
    report.setAttribute('aria-label', '运行报告');
    if (recordedReport) links.append(report);
  }
  toolbar.append(links, sectionRow);
  main.prepend(toolbar);
  main.append(outline);
  main.append(footer);
  if (comparison) main.append(comparison);
  const measure = () => main.style.setProperty('--lesson-offset', `${toolbar.getBoundingClientRect().height + 70}px`);
  measure();
  if ('ResizeObserver' in window) new ResizeObserver(measure).observe(toolbar);
  else window.addEventListener('resize', measure);
  let initialSection = '';
  try { initialSection = decodeURIComponent(location.hash.slice(1)); } catch (_) { /* Ignore malformed URL fragments. */ }
  if (headings.some(h => h.id === initialSection)) select.value = initialSection;
  displaySection();
  updateCurrentSection();
  if (initialSection && headings.some(h => h.id === initialSection)) {
    const restore = () => requestAnimationFrame(() => document.getElementById(initialSection).scrollIntoView({block: 'start'}));
    if (document.readyState === 'complete') restore();
    else window.addEventListener('load', restore, {once: true});
  }
  const positionKey = 'nodefusion-reading:' + location.pathname;
  window.addEventListener('pagehide', () => {
    try { sessionStorage.setItem(positionKey, JSON.stringify({y: window.scrollY, hash: location.hash, sectionMode, width: innerWidth})); } catch (_) { /* Storage may be disabled. */ }
  });
  {
    const restorePosition = () => requestAnimationFrame(() => {
      try {
        const stored = sessionStorage.getItem(positionKey);
        if (stored === null) return;
        const point = JSON.parse(stored);
        const position = typeof point === 'number' ? point : point?.y;
        const hash = typeof point === 'number' ? '' : point?.hash;
        // Pixel offsets from another line width can land in an unrelated section.
        if (hash === location.hash && point?.width === innerWidth && (point?.sectionMode ?? false) === sectionMode && Number.isFinite(position) && position >= 0) window.scrollTo(0, position);
      } catch (_) { /* Keep normal browser navigation when storage is unavailable. */ }
    });
    if (document.readyState === 'complete') restorePosition();
    else window.addEventListener('load', restorePosition, {once: true});
  }
  let scheduled = false;
  window.addEventListener('scroll', () => {
    if (sectionMode) return;
    if (scheduled) return;
    scheduled = true;
    requestAnimationFrame(() => {
      scheduled = false;
      const threshold = toolbar.getBoundingClientRect().bottom + 24;
      let current = headings[0];
      for (const heading of headings) {
        if (heading.getBoundingClientRect().top > threshold) break;
        current = heading;
      }
      if (window.scrollY + window.innerHeight >= document.documentElement.scrollHeight - 2) current = headings.at(-1);
      if (current) {
        select.value = current.id;
        updateCurrentSection();
      }
    });
  }, {passive: true});
  // Fragment links and browser history must reveal their destination in section mode.
  function revealFragment() {
    let id;
    try { id = decodeURIComponent(location.hash.slice(1)); } catch (_) { return; }
    const target = document.getElementById(id);
    const owner = [...sectionNodes].find(([, nodes]) => nodes.some(node => node === target || node.contains(target)));
    if (!owner) return;
    select.value = owner[0];
    displaySection();
    measure();
    target.scrollIntoView({block: 'start'});
    updateCurrentSection();
  }
  window.addEventListener('hashchange', revealFragment);
  main.addEventListener('click', event => {
    const link = event.target.closest('a[href]');
    if (!sectionMode || !link || event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    const url = new URL(link.href, location.href);
    if (url.pathname === location.pathname && url.hash && url.hash === location.hash) revealFragment();
  });
})();
