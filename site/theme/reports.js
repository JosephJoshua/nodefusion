(function () {
  'use strict';
  if (!location.pathname.endsWith('/reports.html')) return;
  const main = document.querySelector('main');
  main.classList.add('report-catalog');
  const groups = [...main.querySelectorAll('h2')].map(heading => {
    const table = heading.nextElementSibling;
    return {heading, table, rows: [...table.querySelectorAll('tbody tr')]};
  });
  const rows = groups.flatMap(group => group.rows.map(row => {
    const report = row.querySelector('a[href^="reports/"]');
    const chapter = report?.getAttribute('href').match(/\/ch([1-8])\//)?.[1] || 'other';
    return {
      row, chapter, source: group.heading.textContent, kernel: row.cells[0].textContent,
      text: (row.textContent + ' ' + [...row.querySelectorAll('a')].map(a => a.href).join(' ')).normalize('NFKC').toLowerCase()
    };
  }));
  const toolbar = document.createElement('form');
  toolbar.className = 'report-toolbar lesson-toolbar';
  toolbar.setAttribute('aria-label', '筛选运行报告');
  function selectField(title, values, format = value => value) {
    const label = document.createElement('label');
    label.textContent = title;
    const select = document.createElement('select');
    for (const value of ['', ...values]) {
      const option = document.createElement('option');
      option.value = value;
      option.textContent = value ? format(value) : '全部';
      select.append(option);
    }
    label.append(select);
    return {label, select};
  }
  const chapter = selectField('章节', ['1', '2', '3', '4', '5', '6', '7', '8', 'other'], value =>
    value === 'other' ? '其他实验' : `第${'一二三四五六七八'[Number(value) - 1]}章`);
  const kernel = selectField('内核', [...new Set(rows.map(item => item.kernel))]);
  const source = selectField('来源', groups.map(group => group.heading.textContent), value =>
    value === '2026A 课程实验' ? '2026A 课程' : value);
  const choices = document.createElement('div');
  choices.className = 'report-choices';
  choices.append(chapter.label, kernel.label, source.label);
  const queryLabel = document.createElement('label');
  queryLabel.className = 'report-query';
  queryLabel.textContent = '查找';
  const query = document.createElement('input');
  query.type = 'search';
  query.placeholder = '章节或实验名称';
  queryLabel.append(query);
  const clear = document.createElement('button');
  clear.type = 'reset';
  clear.textContent = '清除';
  const output = document.createElement('output');
  output.setAttribute('aria-live', 'polite');
  const empty = document.createElement('p');
  empty.textContent = '没有匹配的报告。';
  empty.hidden = true;
  const search = document.createElement('div');
  search.className = 'report-search';
  search.append(queryLabel, clear, output);
  toolbar.append(choices, search);
  main.querySelector('h1').after(toolbar, empty);
  const params = new URLSearchParams(location.search);
  if ([...chapter.select.options].some(o => o.value === params.get('chapter'))) chapter.select.value = params.get('chapter');
  if ([...kernel.select.options].some(o => o.value === params.get('kernel'))) kernel.select.value = params.get('kernel');
  if ([...source.select.options].some(o => o.value === params.get('source'))) source.select.value = params.get('source');
  query.value = params.get('q') || '';
  function filter() {
    const terms = query.value.trim().normalize('NFKC').toLowerCase().split(/\s+/).filter(Boolean);
    let count = 0;
    for (const item of rows) {
      const visible = (!chapter.select.value || item.chapter === chapter.select.value) &&
        (!kernel.select.value || item.kernel === kernel.select.value) &&
        (!source.select.value || item.source === source.select.value) && terms.every(term => item.text.includes(term));
      item.row.hidden = !visible;
      count += visible;
    }
    for (const group of groups) {
      const visible = group.rows.some(row => !row.hidden);
      group.heading.hidden = group.table.hidden = !visible;
    }
    output.textContent = `${count} 份报告`;
    empty.hidden = count !== 0;
    clear.disabled = !chapter.select.value && !kernel.select.value && !source.select.value && !query.value;
    const url = new URL(location.href);
    for (const [key, value] of [['chapter', chapter.select.value], ['kernel', kernel.select.value], ['source', source.select.value], ['q', query.value.trim()]]) {
      if (value) url.searchParams.set(key, value);
      else url.searchParams.delete(key);
    }
    history.replaceState(null, '', url);
  }
  toolbar.addEventListener('submit', event => event.preventDefault());
  toolbar.addEventListener('input', filter);
  toolbar.addEventListener('change', filter);
  toolbar.addEventListener('reset', () => requestAnimationFrame(filter));
  const measure = () => main.style.setProperty('--lesson-offset', `${toolbar.getBoundingClientRect().height + 70}px`);
  measure();
  if ('ResizeObserver' in window) new ResizeObserver(measure).observe(toolbar);
  else window.addEventListener('resize', measure);
  main.addEventListener('click', event => {
    const link = event.target.closest('a[href^="#"]');
    const group = link && groups.find(item => link.hash === '#' + item.heading.id);
    if (!group) return;
    if (group.heading.hidden) {
      source.select.value = group.heading.textContent;
      chapter.select.value = kernel.select.value = query.value = '';
      filter();
    }
  });
  for (const {row} of rows) {
    const report = row.querySelector('a[href^="reports/"]');
    if (report) {
      report.target = '_blank';
      report.rel = 'noopener';
      report.textContent = '运行报告 ↗';
      report.setAttribute('aria-label', `${row.cells[0].textContent} ${row.cells[1].textContent}，在新标签页打开报告`);
    }
    const analysis = row.querySelector('a[href^="ch"]');
    if (analysis) {
      analysis.textContent = '实现分析';
      if (report) row.cells[2].replaceChildren(report, document.createTextNode(' · '), analysis);
    }
  }
  filter();
})();
