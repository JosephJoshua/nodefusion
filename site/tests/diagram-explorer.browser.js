async page => {
  const check = (condition, label) => { if (!condition) throw new Error(label); };
  const base = new URL('/', page.url()).href;
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  for (const width of [320, 390, 900, 1440]) {
    await page.setViewportSize({width, height: 900});
    for (const diagram of ['ch3-switch', 'ch6-blocks', 'ch7-pipe', 'ch8-sync']) {
      await page.goto(base + `diagrams/${diagram}.html`);
      check(await page.locator('#controls').isVisible(), `${diagram} initializes`);
      check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `${diagram} fits ${width}px`);
    }
    await page.goto(base + 'diagrams/ch3-switch.html');
    await page.locator('#scenario').selectOption('alone');
    check(await page.locator('#rcore-count').textContent() === '0', 'rCore skips a self switch');
    check(await page.locator('#ucore-count').textContent() === '2', 'uCore switches through idle');
    await page.locator('#step-timeline button').last().click();
    check(await page.locator('#next').isDisabled(), 'Timeline selects final step');
    await page.goto(base + 'diagrams/ch6-blocks.html');
    await page.locator('#index-bands button').nth(1).click();
    check((await page.locator('#lookup-cost').textContent()).includes('1 个索引块'), 'Index boundary updates lookup depth');
    await page.locator('#offset-scope').selectOption('all');
    await page.locator('#offset-slider').evaluate(el => { el.value = '513'; el.dispatchEvent(new Event('input', {bubbles: true})); });
    check(await page.locator('#offset').inputValue() === '513', 'Slider and numeric offset stay synchronized');
    await page.goto(base + 'diagrams/ch7-pipe.html');
    await page.locator('#writer-run').click();
    check((await page.locator('#unread-arc').getAttribute('d')).includes('A'), 'Unread bytes form a ring arc');
    await page.locator('#byte-index').fill('0');
    check((await page.locator('#byte-value').textContent()).includes('0x'), 'Byte inspector shows stored data');
    await page.goto(base + 'diagrams/ch8-sync.html');
    await page.locator('#scenario').selectOption('semaphore');
    await page.locator('#step-timeline button').nth(2).click();
    check(await page.locator('#waiting-queue .queue-token').allTextContents().then(names => names.join('') === 'AB'), 'FIFO wait order is visible');
    check((await page.locator('#state-changes').textContent()).includes('−2'), 'Changes track semaphore count');
    await page.locator('#step-timeline button').nth(3).click();
    check(await page.locator('#ready-queue .queue-token').allTextContents().then(names => names.join('') === 'A'), 'Running C is distinct from ready A');
  }
  await page.setViewportSize({width: 1440, height: 900});
  await page.goto(base + 'ch3/rcore.html');
  await page.locator('.lesson-toolbar').getByRole('link', {name: '交互图', exact: true}).click();
  await page.waitForFunction(() => document.body.classList.contains('study-side'));
  const menu = page.getByRole('button', {name: '目录', exact: true});
  check(await menu.isVisible(), 'Directory button remains visible beside the right panel');
  await menu.click();
  check(await page.locator('#mdbook-sidebar').isVisible(), 'Directory opens alongside the right panel');
  check(await page.locator('.sidebar-backdrop').isVisible(), 'Overlay provides a dismissal target');
  await page.keyboard.press('Escape');
  check(!(await page.locator('#mdbook-sidebar-toggle-anchor').isChecked()), 'Escape closes the directory');
  check(await menu.evaluate(el => el === document.activeElement), 'Closing returns focus to the menu');
  check(errors.length === 0, errors.join('\n'));
}
