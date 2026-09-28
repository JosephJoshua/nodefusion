async page => {
  const check = (condition, label) => { if (!condition) throw new Error(label); };
  const base = await page.evaluate(() => new URL('./', location.href).href);
  await page.evaluate(() => {
    sessionStorage.removeItem('nodefusion-section-reading');
    sessionStorage.removeItem('nodefusion-study-side');
  });
  for (const width of [320, 390, 900, 1440]) {
    await page.setViewportSize({width, height: 740});
    for (const kernel of ['rcore', 'ucore']) {
      await page.goto(base + `ch8/${kernel}.html`);
      const select = page.getByRole('combobox', {name: '跳转到小节', exact: true});
      check(await select.locator('option').count() === 7, 'Both implementations have seven matching sections');
      await select.selectOption('互斥锁');
      const heading = page.locator('main > h2[id="互斥锁"]');
      const top = await heading.evaluate(el => el.getBoundingClientRect().top);
      await page.locator('.lesson-toolbar').getByRole('link', {name: '交互图', exact: true}).click();
      const frame = page.frameLocator('.study-panel iframe:not([hidden])');
      await frame.locator('html.embedded-diagram').waitFor();
      check(!(await frame.locator('#return-to-lesson').isVisible()), 'Embedded diagram uses parent return');
      check(await frame.locator('#step-title').textContent() === 'A 持有锁', 'Diagram opens at first state');
      await frame.getByRole('button', {name: '下一步', exact: true}).click();
      await frame.getByRole('button', {name: '下一步', exact: true}).click();
      check((await frame.locator('#resource-value').textContent()).includes('B 持有'), 'Unlock transfers lock to B');
      check((await frame.locator('#resource-value').textContent()).includes('locked = 1'), 'Handoff keeps locked set');
      await frame.getByRole('combobox', {name: '机制', exact: true}).selectOption('condvar');
      for (let n = 0; n < 3; n++) await frame.getByRole('button', {name: '下一步', exact: true}).click();
      check(await frame.locator('#queue-value').textContent() === '互斥锁：A', 'Signaled thread waits to reacquire mutex');
      if (width <= 390) {
        check(await frame.locator('#thread-a').evaluate(el => el.getBoundingClientRect().top >= 0), 'Threads stay visible on mobile');
        check(await frame.locator('#resource-value').evaluate(el => el.getBoundingClientRect().bottom <= innerHeight), 'Resource state stays in mobile viewport');
      }
      await page.getByRole('button', {name: '返回正文', exact: true}).click();
      check(await select.inputValue() === '互斥锁', 'Return preserves matching section');
      check(Math.abs(await heading.evaluate(el => el.getBoundingClientRect().top) - top) < 3, 'Return preserves reading position');
      await page.locator('.lesson-toolbar').getByRole('link', {name: '交互图', exact: true}).click();
      check(await frame.locator('#queue-value').textContent() === '互斥锁：A', 'Reopening keeps simulation state');
      await page.getByRole('button', {name: '返回正文', exact: true}).click();
      await page.locator('.lesson-toolbar').getByRole('link', {name: '运行报告', exact: true}).click();
      await frame.locator('#panel-functions.on').waitFor();
      check(await page.locator('select[aria-label="切换运行报告"] option').count() === (kernel === 'rcore' ? 2 : 1), 'Matching chapter reports available in workspace');
      await frame.locator('#function-search').fill('sys_thread_create');
      await page.getByRole('button', {name: '返回正文', exact: true}).click();
      await page.locator('.lesson-toolbar').getByRole('link', {name: '运行报告', exact: true}).click();
      check(await frame.locator('#function-search').inputValue() === 'sys_thread_create', 'Actual function filter persists');
      await page.getByRole('button', {name: '返回正文', exact: true}).click();
      check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `Chapter fits ${width}px`);
      const counterpart = kernel === 'rcore' ? 'uCore' : 'rCore';
      await page.locator('.lesson-toolbar').getByRole('link', {name: counterpart, exact: true}).click();
      check(await select.inputValue() === '互斥锁', 'Implementation switch retains section');
    }
  }
  await page.goto(base + 'diagrams/ch8-sync.html');
  await page.getByRole('combobox', {name: '机制', exact: true}).selectOption('semaphore');
  for (let n = 0; n < 4; n++) await page.getByRole('button', {name: '下一步', exact: true}).click();
  check(await page.locator('#resource-value').textContent() === 'count = 0', 'Two permits handed to waiters');
  check(await page.locator('#queue-value').textContent() === '空', 'Semaphore queue drains');
  check(await page.getByRole('button', {name: '下一步', exact: true}).isDisabled(), 'No step past scenario end');
  await page.getByRole('button', {name: '重置', exact: true}).click();
  check(await page.locator('#resource-value').textContent() === 'count = 0', 'Reset restores initial state');
}
