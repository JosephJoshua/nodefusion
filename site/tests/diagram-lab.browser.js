async page => {
  const base = new URL('/', page.url()).href;
  const check = (condition, label) => { if (!condition) throw new Error(label); };
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.emulateMedia({reducedMotion: 'reduce'});
  for (const width of [320, 390, 720, 900, 1440]) {
    await page.setViewportSize({width, height: width <= 390 ? 740 : 900});
    await page.goto(base + 'diagrams/ch3-switch.html');
    await page.locator('#execution-path [role=button]').nth(4).click();
    check(await page.locator('#switch-count').textContent() === '1', 'Execution plot supports pointer selection');
    await page.locator('#execution-path [role=button]').nth(4).focus();
    await page.keyboard.press('Enter');
    check(await page.locator('#switch-count').textContent() === '1', 'Execution plot selects the actual switch');
    check(await page.locator('.context-row').last().getAttribute('class').then(value => value.includes('active')), 'Kernel context transfer is highlighted');
    await page.keyboard.press('ArrowRight');
    check(await page.locator('#execution').textContent() === 'B：用户态', 'Plot supports keyboard stepping');
    check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'Execution plot fits');
    await page.goto(base + 'diagrams/ch6-blocks.html');
    await page.locator('#boundaries button').last().click();
    check(await page.locator('#offset-slider').getAttribute('min') === '79360', 'Zoom follows the index region');
    await page.getByRole('button', {name: '二级间接块地址项 [1]', exact: true}).click();
    check(await page.locator('#offset').inputValue() === '144896', 'Selecting an outer address updates both indices');
    await page.getByRole('button', {name: '一级间接块地址项 [1]', exact: true}).click();
    check(await page.locator('#offset').inputValue() === '145408', 'Selecting an inner address selects its data block');
    await page.getByRole('button', {name: '块内第 7 字节', exact: true}).click();
    check(await page.locator('#offset').inputValue() === '145415', 'Byte selection updates the offset');
    await page.locator('#next-block').click();
    check(await page.locator('#offset').inputValue() === '145927', 'Block stepping preserves byte offset');
    check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'Index entries fit');

    await page.goto(base + 'diagrams/ch8-sync.html?scenario=condvar');
    await page.getByRole('button', {name: '自由操作', exact: true}).click();
    await page.locator('[data-operation=lock]').click();
    await page.locator('[data-operation=wait]').click();
    await page.locator('#thread-b').click();
    await page.locator('[data-operation=lock]').click();
    await page.locator('[data-operation=signal]').click();
    check((await page.locator('#resource-value').textContent()).includes('B 持有'), 'Signal preserves the notifier lock');
    await page.locator('#thread-a').focus(); await page.keyboard.press('Enter');
    check(await page.locator('#lab-actor').inputValue() === 'A', 'Thread selection supports keyboard');
    check(await page.locator('[data-operation=signal]').isDisabled(), 'cond_wait must reacquire before a new operation');
    await page.locator('[data-operation=lock]').click();
    check((await page.locator('#queue-diagram').getAttribute('aria-label')).includes('等待锁：A'), 'Notified thread can block again on the lock');
    await page.locator('#thread-b').click(); await page.locator('[data-operation=unlock]').click();
    check((await page.locator('#resource-value').textContent()).includes('A 持有'), 'Unlock hands the mutex to A');
    await page.locator('#lab-undo').click();
    check((await page.locator('#resource-value').textContent()).includes('B 持有'), 'Undo restores queues and ownership');
    check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'Synchronization experiment fits');
    if (width <= 390) {
      check(await page.locator('#lab-actions').evaluate(el => el.getBoundingClientRect().bottom <= innerHeight), 'Mobile actions fit');
      check(await page.locator('#queue-diagram').evaluate(el => el.getBoundingClientRect().top >= 0), 'Queue diagram stays visible while operating');
    }
    await page.locator('#scenario').selectOption('semaphore');
    await page.locator('#lab-permits').selectOption('2');
    check(await page.locator('#resource-value').textContent() === 'count = 2', 'Initial permits are configurable');
    await page.locator('[data-operation=down]').click();
    check(await page.locator('#resource-value').textContent() === 'count = 1', 'Down consumes one permit');
    await page.locator('#lab-permits').selectOption('0');
    for (const actor of ['A', 'B', 'C']) {
      await page.locator('#lab-actor').selectOption(actor);
      await page.locator('[data-operation=down]').click();
    }
    check((await page.locator('#lab-message').textContent()).includes('三个线程均已阻塞'), 'All-blocked experiment explains how to recover');
    await page.locator('#lab-undo').click();
    check(await page.locator('[data-operation=up]').isEnabled(), 'Undo restores a runnable thread');

    await page.goto(base + 'diagrams/ch7-pipe.html');
    await page.locator('#buffer-circle').focus(); await page.keyboard.press('ArrowRight');
    check(await page.locator('#byte-index').inputValue() === '1', 'Ring selection supports keyboard');
    await page.locator('#writer-run').click();
    check((await page.locator('#occupancy-chart').getAttribute('aria-label')).includes('0 → 32'), 'Occupancy plot follows real model states');
    await page.locator('.byte-details summary').click();
    check(await page.locator('#pipe-bytes button[data-unread=true]').count() === 8, 'Byte window contains actual unread bytes');
    check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'Pipe experiment fits');
  }
  check(errors.length === 0, errors.join('\n'));
  await page.setViewportSize({width: 320, height: 740});
  for (const kernel of ['rcore', 'ucore']) {
    await page.goto(base + `diagrams/ch7-pipe.html?kernel=${kernel}`);
    check(await page.locator('#writer-run').evaluate(el => el.getBoundingClientRect().bottom <= innerHeight), `${kernel} mobile writer action fits with the buffer`);
    await page.locator('#writer-run').click();
    await page.getByRole('tab', {name: '读进程', exact: true}).click();
    check(await page.locator('#reader-run').evaluate(el => el.getBoundingClientRect().bottom <= innerHeight), `${kernel} mobile reader action fits after writing`);
    check(await page.locator('#ring').evaluate(el => el.getBoundingClientRect().top >= 0), `${kernel} buffer remains visible`);
  }
  await page.emulateMedia({reducedMotion: 'no-preference'});
}
