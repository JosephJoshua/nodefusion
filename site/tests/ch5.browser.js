async (page) => {
  const check = (condition, label) => { if (!condition) throw new Error(label); };
  const base = await page.evaluate(() => new URL('./', location.href).href);
  await page.setViewportSize({width: 1440, height: 900});
  await page.goto(base + 'ch5/rcore.html');
  const sections = page.getByRole('combobox', {name: '跳转到小节', exact: true});
  await sections.selectOption('waitpid-与退出');
  await page.getByRole('button', {name: '对照阅读', exact: true}).click();
  const counterpart = page.getByRole('complementary', {name: 'uCore 对照阅读'});
  await counterpart.getByRole('heading', {name: 'waitpid 与退出', exact: true}).waitFor();
  await sections.selectOption('运行观察');
  await counterpart.getByRole('heading', {name: '运行观察', exact: true}).waitFor();
  const readingY = await page.evaluate(() => scrollY);
  await counterpart.getByRole('link', {name: '打开基础测试报告', exact: true}).click();
  const reports = page.getByRole('combobox', {name: '切换运行报告'});
  check(await reports.locator('option').count() === 3, 'Fifth chapter offers both kernels and the Rust extended workload in place');
  const report = page.frameLocator('.study-panel iframe:not([hidden])');
  await report.locator('#panel-functions.on').waitFor();
  await report.getByRole('button', {name: '事件', exact: true}).click();
  await report.locator('#event-pid').fill('1');
  await report.getByRole('combobox', {name: '事件类型', exact: true}).selectOption('proc.fork');
  await report.locator('#evscroll tbody tr.clickable').first().waitFor();
  const first = report.locator('#evscroll tbody tr.clickable').first();
  check(await first.locator('td').nth(3).textContent() === '1', 'Fork PID filter uses its observed parent');
  check((await first.locator('td').first().textContent()).replaceAll(',', '').trim() === '413158400', 'The documented first C fork is visible');
  await first.click();
  await reports.selectOption({label: '打开扩展测试报告'});
  await report.locator('#panel-functions.on').waitFor();
  await report.locator('#function-search').fill('sys_spawn');
  check(await report.locator('.sequence-function').count() > 0, 'Extended workload includes actual spawn function entries');
  check(!(await report.locator('.sequence-function').first().innerText()).includes('_ZN'),
    'Rust function names are readable in the report');
  await page.getByRole('button', {name: '返回正文', exact: true}).click();
  check(Math.abs(await page.evaluate(() => scrollY) - readingY) < 2, 'Reading position survives cross-kernel report inspection');
  const closeComparison = page.getByRole('button', {name: '关闭对照阅读'});
  if (await closeComparison.count()) await closeComparison.click();
  for (const width of [320, 390, 900, 1440]) {
    await page.setViewportSize({width, height: 900});
    await sections.selectOption('fork-与地址空间');
    check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'Fifth chapter fits ' + width);
    check(await page.locator('main > h2[id="fork-与地址空间"]').evaluate(el => el.getBoundingClientRect().top >= document.querySelector('.lesson-toolbar').getBoundingClientRect().bottom - 1), 'Fork heading clears the reading controls');
    await page.getByRole('link', {name: 'uCore', exact: true}).first().click();
    check(await sections.inputValue() === 'fork-与地址空间', 'Implementation switch preserves the selected mechanism');
    await page.getByRole('link', {name: 'rCore', exact: true}).first().click();
  }
  await page.goto(base + 'ch5/index.html');
  await page.getByRole('combobox', {name: '跳转到小节', exact: true}).selectOption('退出与等待');
  const diagram = page.getByRole('img', {name: 'rCore 与 uCore 在 fork、exit、waitpid 阶段的资源变化'});
  check(await diagram.evaluate(el => el.complete && el.naturalWidth > 0), 'Lifecycle diagram has loaded');
  check(await diagram.evaluate(el => el.getBoundingClientRect().width >= document.querySelector('main').getBoundingClientRect().width * .95), 'Lifecycle diagram uses the reading column rather than the intrinsic SVG fallback width');
  await page.setViewportSize({width: 320, height: 740});
  check(await diagram.evaluate(el => el.getBoundingClientRect().width >= document.querySelector('main').getBoundingClientRect().width * .95), 'Mobile diagram uses the available reading width');
  check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'Lifecycle overview and diagram fit a phone');
}
