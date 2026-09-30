(function () {
  'use strict';
  const name = location.pathname.split('/').pop();
  const chapter = location.pathname.match(/\/ch([1-8])\//)?.[1];
  if (name === 'print.html') return;
  const main = document.querySelector('main');
  if (!main) return;
  if (!chapter) {
    if (!location.pathname.includes('/guides/')) return;
    const headings = [...main.querySelectorAll('h2[id]')];
    const outline = document.createElement('aside');
    outline.className = 'lesson-outline guide-outline';
    const nav = document.createElement('nav');
    nav.setAttribute('aria-label', '本页目录');
    const title = document.createElement('p');
    title.textContent = '本页目录';
    const list = document.createElement('ol');
    for (const heading of headings) {
      const item = document.createElement('li');
      const link = document.createElement('a');
      link.href = '#' + encodeURIComponent(heading.id);
      link.textContent = heading.textContent;
      item.append(link);
      list.append(item);
    }
    nav.append(title, list);
    outline.append(nav);
    main.append(outline);
    return;
  }
  const toolbar = document.createElement('nav');
  toolbar.className = 'lesson-toolbar';
  toolbar.setAttribute('aria-label', '第' + '一二三四五六七八'[Number(chapter) - 1] + '章阅读导航');
  const links = document.createElement('div');
  links.className = 'lesson-links';
  const primary = document.createElement('div');
  primary.className = 'lesson-primary';
  primary.setAttribute('aria-label', '章节页面');
  let diagramLink;
  const chapterLabel = `第${'一二三四五六七八'[Number(chapter) - 1]}章`;
  const pages = [[chapterLabel, 'index.html'], ['rCore', 'rcore.html'], ['uCore', 'ucore.html']];
  const implementation = ['rcore.html', 'ucore.html'].includes(name);
  if (implementation) {
    const chapterLink = [...document.querySelectorAll('#mdbook-sidebar a[href]')].find(link =>
      link.getAttribute('href').endsWith(`ch${chapter}/index.html`));
    const heading = main.querySelector('h1');
    if (heading && chapterLink) {
      const context = document.createElement('p');
      context.className = 'lesson-context';
      context.textContent = chapterLink.textContent;
      heading.before(context);
    }
  }
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
    if (['index.html', 'rcore.html', 'ucore.html'].includes(path)) primary.append(a);
    else links.append(a);
  }
  links.prepend(primary);
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
  let currentSection = '';
  function updateCurrentSection(id) {
    if (!id || id === currentSection) return;
    currentSection = id;
    for (const link of outlineLinks) {
      if (link.dataset.section === currentSection) link.setAttribute('aria-current', 'location');
      else link.removeAttribute('aria-current');
    }
    updateDiagramLink();
    if (counterpartLink) counterpartLink.href = counterpart + '.html#' + encodeURIComponent(matchingSection(currentSection));
    updateComparison();
  }
  function updateDiagramLink() {
    if (!diagramLink) return;
    const params = new URLSearchParams();
    if (name === 'rcore.html' || name === 'ucore.html') params.set('kernel', name.split('.')[0]);
    params.set('return', name + (currentSection ? '#' + currentSection : ''));
    diagramLink.href = '../diagrams/' + diagramPage + '?' + params;
  }
  for (const h of headings) {
    const item = document.createElement('li');
    const link = document.createElement('a');
    link.href = '#' + encodeURIComponent(h.id);
    link.dataset.section = h.id;
    link.textContent = h.textContent;
    link.addEventListener('click', () => updateCurrentSection(h.id));
    item.append(link);
    outlineList.append(item);
    outlineLinks.push(link);
  }
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
    const heading = document.getElementById(currentSection);
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
    if (lastComparisonSection === currentSection) return;
    lastComparisonSection = currentSection;
    const id = matchingSection(currentSection);
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
        renderComparison(comparisonDocument.getElementById(matchingSection(currentSection)) ? matchingSection(currentSection) : otherHeadings[0].id);
        lastComparisonSection = currentSection;
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
  toolbar.append(links);
  main.prepend(toolbar);
  main.append(outline);
  if (comparison) main.append(comparison);
  const measure = () => main.style.setProperty('--lesson-offset', `${toolbar.getBoundingClientRect().height + 70}px`);
  measure();
  if ('ResizeObserver' in window) new ResizeObserver(measure).observe(toolbar);
  else window.addEventListener('resize', measure);
  function sectionForTarget(target) {
    if (!target) return '';
    let owner = '';
    for (const heading of headings) {
      if (heading === target || heading.compareDocumentPosition(target) & Node.DOCUMENT_POSITION_FOLLOWING) owner = heading.id;
      else break;
    }
    return owner;
  }
  let explicitSectionY = null;
  function revealFragment() {
    let id;
    try { id = decodeURIComponent(location.hash.slice(1)); } catch (_) { return; }
    const section = sectionForTarget(document.getElementById(id));
    if (section) explicitSectionY = window.scrollY;
    updateCurrentSection(section || headings[0]?.id);
  }
  revealFragment();
  const positionKey = 'nodefusion-reading:' + location.pathname;
  window.addEventListener('pagehide', () => {
    try { sessionStorage.setItem(positionKey, JSON.stringify({y: window.scrollY, hash: location.hash, width: innerWidth})); } catch (_) { /* Storage may be disabled. */ }
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
        if (hash === location.hash && point?.width === innerWidth && Number.isFinite(position) && position >= 0) window.scrollTo(0, position);
      } catch (_) { /* Keep normal browser navigation when storage is unavailable. */ }
    });
    if (document.readyState === 'complete') restorePosition();
    else window.addEventListener('load', restorePosition, {once: true});
  }
  let scheduled = false;
  function updateFromScroll() {
    if (explicitSectionY !== null) {
      if (Math.abs(window.scrollY - explicitSectionY) < 48) return;
      explicitSectionY = null;
    }
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
      if (current) updateCurrentSection(current.id);
    });
  }
  window.addEventListener('scroll', updateFromScroll, {passive: true});
  window.addEventListener('hashchange', revealFragment);
  if (document.readyState === 'complete') updateFromScroll();
  else window.addEventListener('load', () => { revealFragment(); updateFromScroll(); }, {once: true});
})();
