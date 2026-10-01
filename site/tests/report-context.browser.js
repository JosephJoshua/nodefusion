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
  await page.evaluate(() => sessionStorage.setItem('nodefusion-study-side', 'false'));
  await page.setViewportSize({width: 1440, height: 900});
  await page.goto(base + 'ch4/rcore.html');
  await sectionControl.selectOption('运行观察');
  await page.getByRole('button', {name: '对照阅读', exact: true}).click();
  const pane = page.getByRole('complementary', {name: 'uCore 对照阅读'});
  await pane.getByRole('heading', {name: '运行观察', exact: true}).waitFor();
  const choices = page.getByRole('combobox', {name: '切换运行报告'});
  const readingY = await page.evaluate(() => scrollY);
  const pages = page.context().pages().length;
  await pane.getByRole('link', {name: '页表实验', exact: true}).click();
  const frame = page.frameLocator('.study-panel iframe:not([hidden])');
  await frame.locator('#panel-functions.on').waitFor();
  check(page.context().pages().length === pages, 'Comparison report opens without a new tab');
  check(await choices.locator('option').count() === 3, 'Both implementations share the report selector');
  check((await choices.inputValue()).endsWith('ucore-2026A-ch4-pagetable.html'), 'Comparison opens the chosen workload');
  check((await page.getByRole('link', {name: '运行报告', exact: true}).getAttribute('href')).includes('ucore-2026A-ch4-pagetable.html'), 'Native new-tab navigation points to the selected report too');
  check(await choices.locator('option:checked').textContent() === 'uCore · 页表实验', 'Counterpart report identifies its kernel');
  await frame.locator('#function-search').fill('uvmunmap');
  await page.getByRole('button', {name: '返回正文', exact: true}).focus();
  await page.keyboard.press('Escape');
  check(!(await page.locator('.study-panel').isVisible()), 'Escape closes the top report');
  check(await pane.isVisible(), 'Escape preserves comparison underneath');
  check(await pane.getByRole('link', {name: '页表实验', exact: true}).evaluate(el => el === document.activeElement), 'Close restores the comparison link focus');
  check(Math.abs(await page.evaluate(() => scrollY) - readingY) < 2, 'Comparison report round trip keeps reading position');
  await page.getByRole('link', {name: '运行报告', exact: true}).click();
  check((await choices.inputValue()).endsWith('ucore-2026A-ch4-pagetable.html'), 'Toolbar resumes the selected report');
  check(await frame.locator('#function-search').inputValue() === 'uvmunmap', 'Resuming keeps the real function filter');
  await page.getByRole('button', {name: '返回正文', exact: true}).click();
  await page.locator('main > p').getByRole('link', {name: '查看内存管理报告', exact: true}).click();
  await frame.locator('#panel-functions.on').waitFor();
  check((await choices.inputValue()).endsWith('rcore-2026A-ch4-observed.html'), 'Explicit in-text link still opens its own report');
  await page.getByRole('button', {name: '返回正文', exact: true}).click();
  await pane.getByRole('link', {name: '基础批次', exact: true}).click();
  await frame.locator('#panel-functions.on').waitFor();
  await sectionControl.selectOption('映射与回收');
  await pane.getByRole('heading', {name: '映射与回收', exact: true}).waitFor();
  await page.getByRole('button', {name: '返回正文', exact: true}).click();
  check(await page.getByRole('link', {name: '运行报告', exact: true}).evaluate(el => el === document.activeElement), 'Removed comparison opener falls back to the report control');
  await page.keyboard.press('Escape');
  check(!(await pane.isVisible()), 'Second Escape closes comparison after the report');
  await page.goto(base + 'ch4/ucore.html');
  await page.getByRole('link', {name: '运行报告', exact: true}).click();
  await frame.locator('#panel-functions.on').waitFor();
  await choices.selectOption({label: '页表实验'});
  await frame.locator('#panel-functions.on').waitFor();
  const selectedPath = await choices.inputValue();
  await frame.locator('#function-search').fill('walkaddr');
  await frame.locator('#function-grouping').selectOption('caller');
  await frame.getByRole('button', {name: '上一帧', exact: true}).click();
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  check(await frame.locator('#function-search').inputValue() === 'walkaddr', 'Timeline change retains function search');
  check(await frame.locator('.trace-panel:not([hidden])').count() === 1, 'One navigator remains active');
  check(await frame.locator('#function-grouping').inputValue() === 'caller', 'Timeline change retains grouping');
  await page.getByRole('button', {name: '返回正文', exact: true}).click();
  await page.setViewportSize({width: 390, height: 844});
  await page.getByRole('link', {name: '运行报告', exact: true}).click();
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  check(await choices.inputValue() === selectedPath, 'Narrow screen resumes the chosen workload');
  check(await frame.locator('#function-search').inputValue() === 'walkaddr', 'Narrow screen retains its report filter');
  check(await frame.locator('#function-grouping').inputValue() === 'caller', 'Narrow screen retains grouping');
  await frame.locator('#function-search').fill('uvmunmap');
  check(await frame.locator('#panel-functions').evaluate(el => el.scrollHeight <= el.clientHeight + 1), 'Navigator has no outer scrollbar');
  await page.getByRole('button', {name: '返回正文', exact: true}).click();
}
