async (page) => {
  const check = (condition, label) => { if (!condition) throw new Error(label); };
  const base = await page.evaluate(() => new URL('./', location.href).href);
  await page.goto(base + 'reports.html');
  const total = await page.locator('tbody tr').count();
  const courseTotal = await page.locator('main h2').first().evaluate(el => el.nextElementSibling.querySelectorAll('tbody tr').length);
  const chapterFiveTotal = await page.locator('tbody tr').evaluateAll(rows => rows.filter(row => row.querySelector('a[href*="/ch5/"]')).length);
  await page.setViewportSize({width: 1280, height: 900});
  check(await page.locator('main.report-catalog').evaluate(el => el.getBoundingClientRect().width > 800), 'Report catalog uses desktop width');
  check(await page.locator('.report-query input').evaluate(el => el.getBoundingClientRect().width > 180), 'Report search has usable desktop width');
  check((await page.locator('tbody tr').first().locator('td').last().innerText()).indexOf('运行报告') <
    (await page.locator('tbody tr').first().locator('td').last().innerText()).indexOf('实现分析'), 'Report actions use a consistent order');
  const directory = page.getByRole('button', {name: '目录', exact: true});
  if (!(await page.locator('#mdbook-sidebar-toggle-anchor').isChecked())) await directory.click();
  await page.setViewportSize({width: 320, height: 720});
  await page.waitForFunction(() => !document.getElementById('mdbook-sidebar-toggle-anchor').checked);
  check(!(await page.locator('#mdbook-sidebar-toggle-anchor').isChecked()), 'Collapse directory on narrow resize');
  await directory.focus();
  await page.keyboard.press('Enter');
  check(await page.locator('#mdbook-sidebar-toggle-anchor').isChecked(), 'Keyboard opens directory');
  await page.keyboard.press('Escape');
  check(!(await page.locator('#mdbook-sidebar-toggle-anchor').isChecked()), 'Escape closes directory');
  check(await directory.evaluate(el => el === document.activeElement), 'Escape returns focus');
  await page.getByRole('searchbox', {name: '查找', exact: true}).fill('no-such-report');
  check(await page.locator('tbody tr:visible').count() === 0, 'Empty results');
  await page.getByRole('button', {name: '清除', exact: true}).click();
  await page.waitForFunction(count => document.querySelector('output').textContent === `${count} 份报告`, total);
  await page.getByRole('combobox', {name: '章节', exact: true}).selectOption('5');
  check(await page.locator('tbody tr:visible').count() === chapterFiveTotal, 'Chapter filter');
  check(new URL(page.url()).searchParams.get('chapter') === '5', 'Chapter filter URL');
  await page.reload();
  check(await page.getByRole('combobox', {name: '章节', exact: true}).inputValue() === '5', 'Restore chapter filter URL');
  await page.getByRole('button', {name: '清除', exact: true}).click();
  await page.waitForFunction(count => document.querySelector('output').textContent === `${count} 份报告`, total);
  await page.getByRole('combobox', {name: '来源', exact: true}).selectOption('2026A 课程实验');
  check(await page.locator('tbody tr:visible').count() === courseTotal, 'Source filter');
  await page.reload();
  check(await page.locator('tbody tr:visible').count() === courseTotal, 'Restore filter URL');
  check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'Catalog fits 320px');
  await page.getByRole('button', {name: '清除', exact: true}).click();
  await page.waitForFunction(count => document.querySelector('output').textContent === `${count} 份报告`, total);
  await page.evaluate(() => window.scrollTo(0, 1000));
  check(await page.locator('.report-toolbar').evaluate(el => Math.abs(el.getBoundingClientRect().top - 50) < 2), 'Filter toolbar stays visible');
  await page.goto(base + 'ch3/rcore.html');
  check((await page.locator('.lesson-context').textContent()).includes('第三章：任务切换与调度'), 'Implementation shows chapter context');
  check(await page.getByRole('navigation', {name: '第三章阅读导航'}).getByRole('link', {name: '第三章'}).isVisible(), 'Chapter tab stays identifiable');
  check(await page.locator('#mdbook-sidebar .chapter > .chapter-item > .section').evaluateAll(nodes =>
    nodes.filter(node => getComputedStyle(node).display !== 'none').length) === 1, 'Directory expands only the current chapter');
  check(await page.locator('main > h2:visible').count() > 1, 'Chapter uses continuous reading');
  await page.setViewportSize({width: 1720, height: 900});
  const outline = page.getByRole('navigation', {name: '本页小节', exact: true});
  check(await outline.isVisible(), 'Wide screen shows the section outline');
  await outline.getByRole('link', {name: '运行观察', exact: true}).click();
  await page.waitForFunction(() => document.querySelector('.lesson-outline [aria-current="location"]')?.dataset.section === '运行观察');
  check(await page.evaluate(() => document.getElementById('运行观察').getBoundingClientRect().top >= document.querySelector('.lesson-toolbar').getBoundingClientRect().bottom - 1), 'Anchor clears toolbar');
  await page.getByRole('link', {name: '交互图', exact: true}).click();
  await page.frameLocator('iframe[title="交互图"]').getByRole('link', {name: '返回阅读位置'}).click();
  check(decodeURIComponent(new URL(page.url()).hash) === '#运行观察', 'Diagram returns to section');
  for (const kernel of ['rcore', 'ucore']) {
    await page.goto(base + `ch1/${kernel}.html#运行观察`);
    await page.setViewportSize({width: 320, height: 720});
    check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'Chapter one fits narrow screen');
    await page.getByRole('link', {name: '运行报告', exact: true}).click();
    await page.frameLocator('iframe[title="运行报告"]').locator('#panel-functions.on').waitFor();
    await page.getByRole('button', {name: '返回正文', exact: true}).click();
    check(decodeURIComponent(new URL(page.url()).hash) === '#运行观察', 'Report return retains the section');
  }
  await page.goto(base);
  check(await page.locator('.chapter-index-row').count() === 8, 'Home lists eight chapters');
  for (const row of await page.locator('.chapter-index-row').all()) {
    check(await row.locator('.chapter-actions a').count() === 3, 'Each chapter links both implementations and reports');
  }
  await page.getByRole('link', {name: '添加内核支持'}).last().click();
  check(await page.getByRole('heading', {name: '添加内核支持', exact: true}).count() === 1, 'Wiki authoring guide appears in the site');
  await page.setViewportSize({width: 1440, height: 900});
  const guideOutline = page.getByRole('navigation', {name: '本页目录'});
  check(await guideOutline.isVisible(), 'Long guide has a desktop outline');
  await guideOutline.getByRole('link', {name: '准备内核构建'}).click();
  check(decodeURIComponent(new URL(page.url()).hash) === '#准备内核构建', 'Guide outline opens the selected heading');
  await page.getByRole('link', {name: 'Manifest 语法参考'}).last().click();
  check(await page.getByRole('heading', {name: 'Manifest 语法参考', exact: true}).count() === 1, 'Wiki reference appears in the site');
}
