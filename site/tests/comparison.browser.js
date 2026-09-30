async (page) => {
  const check = (condition, label) => { if (!condition) throw new Error(label); };
  const base = await page.evaluate(() => new URL('./', location.href).href);
  const sectionControl = {
    async selectOption(value) {
      const headings = page.locator('main > h2[id]');
      const id = typeof value === 'string' ? value : value.label || await headings.nth(value.index).getAttribute('id');
      await page.waitForFunction(() => Math.abs(parseFloat(document.querySelector('main').style.getPropertyValue('--lesson-offset')) - document.querySelector('.lesson-toolbar').getBoundingClientRect().height - 70) < 1);
      await page.evaluate(id => {
        const heading = document.getElementById(id);
        if (!heading) throw new Error('Missing section: ' + id);
        location.hash = encodeURIComponent(id);
        heading.scrollIntoView({block: 'start'});
        window.dispatchEvent(new HashChangeEvent('hashchange'));
      }, id);
      await page.waitForFunction(id => document.querySelector('.lesson-outline [aria-current="location"]')?.dataset.section === id, id);
    },
    inputValue: () => page.locator('.lesson-outline [aria-current="location"]').getAttribute('data-section'),
    locator: () => page.locator('main > h2[id]')
  };
  await page.setViewportSize({width: 1440, height: 900});
  await page.goto(base + 'ch3/rcore.html');
  await sectionControl.selectOption('让出与选择下一个任务');
  await page.getByRole('link', {name: 'uCore', exact: true}).first().click();
  check(await sectionControl.inputValue() === '让出处理器', 'Switch implementations at matching mechanism');
  await page.getByRole('link', {name: 'rCore', exact: true}).first().click();
  const toggle = page.getByRole('button', {name: '对照阅读', exact: true});
  const beforeTop = await page.locator('h2[id="让出与选择下一个任务"]').evaluate(el => el.getBoundingClientRect().top);
  await toggle.click();
  const pane = page.getByRole('complementary', {name: 'uCore 对照阅读'});
  await pane.getByRole('heading', {name: '让出处理器', exact: true}).waitFor();
  check(Math.abs(await page.locator('main > h2[id="让出与选择下一个任务"]').evaluate(el => el.getBoundingClientRect().top) - beforeTop) < 3, 'Opening comparison keeps reading anchor');
  check(await toggle.getAttribute('aria-expanded') === 'true', 'Comparison expanded state');
  check(await page.evaluate(() => new Set([...document.querySelectorAll('[id]')].map(el => el.id)).size === document.querySelectorAll('[id]').length), 'Comparison does not duplicate fragment IDs');
  await sectionControl.selectOption('运行观察');
  await pane.getByRole('heading', {name: '运行观察', exact: true}).waitFor();
  const readingY = await page.evaluate(() => window.scrollY);
  const body = pane.getByLabel('对照正文', {exact: true});
  await body.focus();
  await page.keyboard.press('PageDown');
  if (await body.evaluate(el => el.scrollHeight > el.clientHeight)) {
    await page.waitForFunction(() => document.querySelector('.comparison-body').scrollTop > 0);
  }
  check(await page.evaluate(() => window.scrollY) === readingY, 'Keyboard scrolls comparison without moving primary reading');
  await pane.getByRole('combobox', {name: '对照小节'}).selectOption('进程表与上下文');
  check(!(await pane.getByRole('checkbox', {name: '跟随正文'}).isChecked()), 'Manual section disables following');
  await sectionControl.selectOption('时钟抢占与退出');
  check(await pane.getByRole('combobox', {name: '对照小节'}).inputValue() === '进程表与上下文', 'Manual comparison stays selected');
  await pane.getByRole('checkbox', {name: '跟随正文'}).check();
  await pane.getByRole('heading', {name: '退出与批次结束', exact: true}).waitFor();
  await sectionControl.selectOption('运行观察');
  await pane.getByRole('heading', {name: '运行观察', exact: true}).waitFor();
  await page.getByRole('link', {name: '运行报告', exact: true}).click();
  await page.frameLocator('iframe[title="运行报告"]').locator('#panel-functions.on').waitFor();
  check(await pane.isVisible(), 'Opening a report keeps the comparison open');
  const stacked = page.getByRole('button', {name: '上下分屏', exact: true});
  if (await stacked.isVisible()) await stacked.click();
  const resize = page.getByRole('separator', {name: '调整报告高度'});
  for (const [height, key] of [[900, 'Home'], [900, 'End'], [680, 'Home'], [680, 'End']]) {
    await page.setViewportSize({width: 1440, height});
    await resize.focus();
    await page.keyboard.press(key);
    check(await pane.locator('.comparison-panel').evaluate(el => {
      const bounds = el.getBoundingClientRect();
      return bounds.top >= 50 && bounds.bottom <= document.querySelector('.study-panel').getBoundingClientRect().top;
    }), 'Comparison fits above report at both resize bounds');
    const y = await page.evaluate(() => window.scrollY);
    await body.focus();
    await page.keyboard.press('End');
    await page.waitForFunction(() => {
      const body = document.querySelector('.comparison-body');
      return body.scrollTop + body.clientHeight >= body.scrollHeight - 2;
    });
    check(await page.evaluate(() => window.scrollY) === y, 'Comparison scroll does not move primary reading with report open');
    const lastLink = body.getByRole('link').last();
    await lastLink.focus();
    check(await lastLink.evaluate(el => {
      const bounds = el.getBoundingClientRect();
      const body = el.closest('.comparison-body').getBoundingClientRect();
      return bounds.top >= body.top && bounds.bottom <= body.bottom && bounds.bottom <= document.querySelector('.study-panel').getBoundingClientRect().top;
    }), 'Last comparison link and keyboard focus remain visible above report');
  }
  await page.getByRole('button', {name: '返回正文', exact: true}).click();
  check(await pane.isVisible(), 'Returning from report keeps comparison open');
  await page.setViewportSize({width: 1440, height: 600});
  await page.getByRole('link', {name: '运行报告', exact: true}).click();
  check(await page.getByRole('dialog', {name: '阅读资料'}).isVisible(), 'Short desktop viewport opens report full screen');
  check(!(await resize.isVisible()), 'Short viewport does not offer a cramped split');
  await page.getByRole('button', {name: '返回正文', exact: true}).click();
  check(await pane.isVisible(), 'Short viewport report round trip retains comparison');
  await page.setViewportSize({width: 1440, height: 900});
  await page.keyboard.press('Escape');
  check(!(await pane.isVisible()), 'Escape closes comparison');
  check(await toggle.evaluate(el => el === document.activeElement), 'Escape restores focus');
  await page.getByRole('link', {name: '运行报告', exact: true}).click();
  check(await page.locator('.lesson-outline nav').evaluate(el => el.getBoundingClientRect().bottom <= document.querySelector('.study-panel').getBoundingClientRect().top), 'Section outline fits above report too');
  await page.getByRole('button', {name: '返回正文', exact: true}).click();
  await page.goto(base + 'ch3/rcore.html');
  for (const width of [1200, 1440, 1720]) {
    await page.setViewportSize({width, height: 900});
    const directory = page.getByRole('button', {name: '目录', exact: true});
    if (!(await page.locator('#mdbook-sidebar-toggle-anchor').isChecked())) await directory.click();
    await toggle.click();
    await pane.getByRole('heading').first().waitFor();
    check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `Comparison fits ${width}px with chapter directory`);
    await page.waitForFunction(width => {
      const bounds = document.querySelector('.comparison-panel').getBoundingClientRect();
      return bounds.right <= width && bounds.top >= 50;
    }, width);
    const bounds = await pane.locator('.comparison-panel').boundingBox();
    check(bounds.x + bounds.width <= width && bounds.y >= 50, `Comparison stays in viewport at ${width}px: ${JSON.stringify(bounds)}`);
    await pane.getByRole('button', {name: '关闭对照阅读'}).click();
    await directory.click();
  }
  await toggle.click();
  await page.setViewportSize({width: 390, height: 844});
  await page.waitForFunction(() => document.querySelector('.lesson-comparison').hidden);
  check(!(await pane.isVisible()), 'Narrow resize closes comparison');
  check(!(await toggle.isVisible()), 'Narrow layout uses implementation navigation');
  check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'Narrow reading fits viewport');
  for (const kernel of ['rcore', 'ucore']) {
    await page.goto(base + `ch1/${kernel}.html`);
    await sectionControl.selectOption('输出与终止');
    await page.locator('.lesson-links a').filter({hasText: kernel === 'rcore' ? 'uCore' : 'rCore'}).click();
    check(await sectionControl.inputValue() === '输出与终止', 'Chapter one implementation switch keeps topic');
  }
  await page.setViewportSize({width: 1440, height: 900});
  await page.goto(base + 'ch3/rcore.html');
  let requests = 0;
  await page.route('**/ch3/ucore.html', async route => {
    requests++;
    if (requests === 1) await route.abort();
    else await route.continue();
  });
  await page.getByRole('button', {name: '对照阅读', exact: true}).click();
  await page.getByRole('button', {name: '重试', exact: true}).click();
  await page.getByRole('complementary', {name: 'uCore 对照阅读'}).getByRole('heading').first().waitFor();
  await page.unroute('**/ch3/ucore.html');
  check(requests === 2, 'Failed comparison request retries');
}
