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
  await page.evaluate(() => {
    sessionStorage.removeItem('nodefusion-study-side');
    sessionStorage.removeItem('nodefusion-study-width');
  });
  await page.setViewportSize({width: 1440, height: 900});
  await page.goto(base + 'ch5/rcore.html');
  await sectionControl.selectOption('fork-与地址空间');
  await page.locator('.lesson-toolbar').getByRole('link', {name: '运行报告', exact: true}).click();
  const frame = page.frameLocator('.study-panel iframe:not([hidden])');
  await frame.locator('#panel-functions.on').waitFor();
  await frame.locator('#function-search').fill('fork');
  const heading = page.locator('main > h2[id="fork-与地址空间"]');
  const initialTop = await heading.evaluate(el => el.getBoundingClientRect().top);
  await page.waitForFunction(() => document.body.classList.contains('study-side'));
  check(await page.getByRole('button', {name: '上下分屏', exact: true}).isVisible(), 'Fresh readers open directly into side-by-side reading');
  check(await page.locator('.study-panel').evaluate(el => el.getBoundingClientRect().height > innerHeight - 70), 'Side report uses full reading height');
  check(await page.locator('.content').evaluate(el => el.getBoundingClientRect().right <= document.querySelector('.study-panel').getBoundingClientRect().left + 1), 'Report and reading do not overlap');
  check(!(await page.getByRole('separator', {name: '调整报告高度'}).isVisible()), 'Side view omits vertical resize');
  check(Math.abs(await heading.evaluate(el => el.getBoundingClientRect().top) - initialTop) < 3, 'Docking preserves the reading anchor');
  check(await frame.locator('#function-search').inputValue() === 'fork', 'Docking preserves the actual report filter');
  const widthResize = page.getByRole('separator', {name: '调整正文宽度'});
  await widthResize.focus();
  await page.keyboard.press('ArrowRight');
  check(await widthResize.getAttribute('aria-valuenow') === '50', 'Keyboard adjusts the reading pane width');
  await page.keyboard.press('Home');
  check(await page.locator('.content main').evaluate(el => el.getBoundingClientRect().width >= 500), 'Minimum reading width remains usable');
  await page.keyboard.press('End');
  check(await page.locator('.study-panel').evaluate(el => el.getBoundingClientRect().width >= 559), 'Maximum reading width leaves space for the report');
  const handle = await widthResize.boundingBox();
  await page.mouse.move(handle.x + handle.width / 2, handle.y + handle.height / 2);
  await page.mouse.down();
  await page.mouse.move(1440 * .52, handle.y + handle.height / 2);
  await page.mouse.up();
  check(await widthResize.getAttribute('aria-valuenow') === '52', 'Pointer adjusts the split in place');
  check(Math.abs(await heading.evaluate(el => el.getBoundingClientRect().top) - initialTop) < 3, 'Width resizing preserves the reading anchor');
  check(await frame.locator('#function-search').inputValue() === 'fork', 'Width resizing preserves the actual function filter');
  await sectionControl.selectOption('exec-与程序装载');
  check(await page.locator('main > h2[id="exec-与程序装载"]').isVisible(), 'Reader can change mechanisms alongside the report');
  for (const width of [1200, 1440, 1720]) {
    await page.setViewportSize({width, height: 900});
    check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `Side view fits ${width}px`);
    check(await page.locator('.content main').evaluate(el => el.getBoundingClientRect().width >= 500), 'Side reading retains a usable line width');
    check(await frame.locator('#function-search').inputValue() === 'fork', 'Viewport change preserves filtering');
  }
  await page.setViewportSize({width: 390, height: 844});
  await page.getByRole('dialog', {name: '阅读资料'}).waitFor();
  check(!(await page.getByRole('button', {name: '左右并排', exact: true}).isVisible()), 'Narrow screen omits docking control');
  await page.setViewportSize({width: 1440, height: 900});
  await page.getByRole('button', {name: '上下分屏', exact: true}).waitFor();
  await page.getByRole('button', {name: '展开', exact: true}).click();
  check(await page.locator('.page-wrapper').evaluate(el => el.inert), 'Expanded report keeps hidden reading controls out of focus');
  await page.getByRole('button', {name: '收起', exact: true}).click();
  check(await page.locator('body').evaluate(el => el.classList.contains('study-side')), 'Collapsing restores side view');
  const topBeforeClose = await page.locator('main > h2[id="exec-与程序装载"]').evaluate(el => el.getBoundingClientRect().top);
  await page.getByRole('button', {name: '返回正文', exact: true}).click();
  const topAfterClose = await page.locator('main > h2[id="exec-与程序装载"]').evaluate(el => el.getBoundingClientRect().top);
  check(Math.abs(topAfterClose - topBeforeClose) < 3, `Closing restores the reading anchor: ${topBeforeClose} -> ${topAfterClose}`);
  await page.waitForTimeout(350);
  check(Math.abs(await page.locator('main > h2[id="exec-与程序装载"]').evaluate(el => el.getBoundingClientRect().top) - topBeforeClose) < 3, 'Reading anchor remains stable after directory restoration');
  await page.getByRole('button', {name: '对照阅读', exact: true}).click();
  const comparison = page.getByRole('complementary', {name: 'uCore 对照阅读'});
  await comparison.getByRole('heading').first().waitFor();
  await page.getByRole('combobox', {name: '对照小节', exact: true}).selectOption('运行观察');
  await comparison.locator('a[href*="/reports/"]').first().click();
  check(!(await comparison.isVisible()), `Side layout keeps two useful panes rather than three cramped panes: ${await page.locator('body').getAttribute('class')}`);
  check(await page.locator('body').evaluate(el => el.classList.contains('study-side')), 'Reopening remembers preferred docking');
  await page.getByRole('button', {name: '上下分屏', exact: true}).click();
  check(await page.getByRole('separator', {name: '调整报告高度'}).isVisible(), 'Bottom layout restores vertical resize');
  await page.getByRole('button', {name: '返回正文', exact: true}).click();
  check(await page.locator('.lesson-toolbar').getByRole('link', {name: '运行报告', exact: true}).evaluate(el => el === document.activeElement), 'Hidden comparison opener returns focus to visible report control');
  await page.reload();
  check(Math.abs(await page.evaluate(() => Number(sessionStorage.getItem('nodefusion-study-width'))) - 52) < .00001, 'Reload retains the preferred width');
  await page.locator('.lesson-toolbar').getByRole('link', {name: '运行报告', exact: true}).click();
  check(!(await page.locator('body').evaluate(el => el.classList.contains('study-side'))), 'Reload remembers bottom layout choice');
  await page.getByRole('button', {name: '返回正文', exact: true}).click();
  await page.locator('.lesson-toolbar').getByRole('link', {name: '运行报告', exact: true}).click();
  await page.getByRole('button', {name: '左右并排', exact: true}).click();
  check(await widthResize.getAttribute('aria-valuenow') === '52', 'Returning to side mode restores its width');
  await widthResize.dblclick();
  check(await widthResize.getAttribute('aria-valuenow') === '48', 'Double click restores the default split');
  await page.getByRole('button', {name: '返回正文', exact: true}).click();
}
