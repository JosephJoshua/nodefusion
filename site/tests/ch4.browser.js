async (page) => {
  const check = (condition, label) => { if (!condition) throw new Error(label); };
  const base = await page.evaluate(() => new URL('./', location.href).href);
  await page.setViewportSize({width: 1440, height: 900});
  await page.goto(base + 'ch4/rcore.html');
  const section = page.getByRole('combobox', {name: '跳转到小节', exact: true});
  await section.selectOption('用户地址检查');
  await page.getByRole('button', {name: '对照阅读', exact: true}).click();
  const comparison = page.getByRole('complementary', {name: 'uCore 对照阅读'});
  await comparison.getByRole('heading', {name: '用户地址检查', exact: true}).waitFor();
  await section.selectOption('映射与回收');
  await comparison.getByRole('heading', {name: '映射与回收', exact: true}).waitFor();
  await page.keyboard.press('Escape');
  await page.getByRole('link', {name: 'uCore', exact: true}).first().click();
  check(await section.inputValue() === '映射与回收', 'Chapter four counterpart retains mechanism');
  await section.selectOption('运行观察');
  await page.evaluate(() => scrollBy(0, 55));
  const y = await page.evaluate(() => scrollY);
  await page.getByRole('link', {name: '运行报告', exact: true}).click();
  const choices = page.getByRole('combobox', {name: '切换运行报告'});
  check(await choices.locator('option').count() === 2, 'Chapter four workloads available in place');
  const original = await choices.inputValue();
  const report = page.frameLocator('.study-panel iframe:not([hidden])');
  await report.locator('#panel-functions.on').waitFor();
  await report.locator('#function-search').fill('useraddr');
  const experiment = await choices.locator('option').evaluateAll(options => options.find(o => o.value.includes('pagetable.html')).value);
  await choices.selectOption(experiment);
  await report.locator('#panel-functions.on').waitFor();
  check((await page.locator('.study-panel iframe:not([hidden])').getAttribute('src')).includes('pagetable.html'), 'Experiment selected without returning to prose');
  await choices.selectOption(original);
  check(await report.locator('#function-search').inputValue() === 'useraddr', 'Returning to batch preserves function filter');
  check(await page.evaluate(() => scrollY) === y, 'Switching workload keeps exact reading position');
  await page.getByRole('button', {name: '返回正文', exact: true}).click();
  for (const width of [320, 390, 900, 1720]) {
    await page.setViewportSize({width, height: 900});
    await section.selectOption('装载与地址空间');
    check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'Chapter fits ' + width);
    check(await page.evaluate(() => document.getElementById('装载与地址空间').getBoundingClientRect().top >= document.querySelector('.lesson-toolbar').getBoundingClientRect().bottom - 1), 'Section clears toolbar at ' + width);
  }
  await page.goto(base + 'ch4/index.html');
  await page.getByRole('combobox', {name: '跳转到小节', exact: true}).selectOption('sv39-地址转换');
  const image = page.getByRole('img', {name: 'Sv39 三级页表与页内偏移'});
  check(await image.evaluate(el => el.complete && el.naturalWidth > 0), 'Sv39 diagram loaded');
  await page.setViewportSize({width: 320, height: 720});
  check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'Sv39 diagram and introduction fit narrow screen');
}
