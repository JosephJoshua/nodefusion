async page => {
  const check = (condition, label) => { if (!condition) throw new Error(label); };
  const base = await page.evaluate(() => new URL('./', location.href).href);
  for (const width of [320, 390, 900, 1440]) {
    await page.setViewportSize({width, height: 900});
    await page.goto(base + 'diagrams/ch7-pipe.html');
    await page.getByRole('button', {name: '运行写进程', exact: true}).click();
    check(await page.locator('#occupancy').textContent() === '32 / 32 字节', 'Writer fills actual Rust capacity');
    check((await page.locator('#result').textContent()).includes('请求仍未返回'), 'Full buffer leaves write pending');
    if (width <= 720) await page.getByRole('tab', {name: '读进程', exact: true}).click();
    await page.getByRole('button', {name: '运行读进程', exact: true}).click();
    check(await page.locator('#occupancy').textContent() === '0 / 32 字节', 'Reader consumes available bytes');
    check((await page.locator('#reader-status').textContent()).includes('32 / 40'), 'Rust reader keeps partial progress');
    if (width <= 720) await page.getByRole('tab', {name: '写进程', exact: true}).click();
    await page.getByRole('button', {name: '运行写进程', exact: true}).click();
    check((await page.locator('#writer-status').textContent()).includes('返回 40'), 'Rust writer resumes original request');
    await page.getByRole('button', {name: '关闭写端', exact: true}).click();
    if (width <= 720) await page.getByRole('tab', {name: '读进程', exact: true}).click();
    await page.getByRole('button', {name: '运行读进程', exact: true}).click();
    check((await page.locator('#reader-status').textContent()).includes('返回 40'), 'Reader drains bytes after writer closes');
    await page.getByRole('button', {name: '上一步', exact: true}).click();
    check((await page.locator('#reader-status').textContent()).includes('32 / 40'), 'Undo preserves the suspended call');
    await page.getByRole('combobox', {name: '内核', exact: true}).selectOption('ucore');
    if (width <= 720) await page.getByRole('tab', {name: '写进程', exact: true}).click();
    await page.getByRole('button', {name: '运行写进程', exact: true}).click();
    check(await page.locator('#occupancy').textContent() === '512 / 512 字节', 'C uses its real capacity');
    if (width <= 720) await page.getByRole('tab', {name: '读进程', exact: true}).click();
    await page.getByRole('button', {name: '运行读进程', exact: true}).click();
    check((await page.locator('#reader-status').textContent()).includes('返回 512'), 'C returns currently available bytes');
    await page.getByRole('combobox', {name: '示例', exact: true}).selectOption('wrap');
    if (width <= 720) await page.getByRole('tab', {name: '写进程', exact: true}).click();
    await page.getByRole('button', {name: '运行写进程', exact: true}).click();
    check((await page.locator('#result').textContent()).includes('copyin(4)') && (await page.locator('#result').textContent()).includes('copyin(8)'), 'C ring wrap splits contiguous copies');
    check(await page.locator('#occupancy').textContent() === '16 / 512 字节', 'Wrap retains earlier unread bytes');
    check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `Pipe view fits ${width}px`);
    await page.getByRole('combobox', {name: '示例', exact: true}).selectOption('empty');
    if (width <= 720) {
      const read = page.getByRole('tab', {name: '读进程', exact: true});
      await read.focus(); await page.keyboard.press('ArrowLeft');
      check(await page.getByRole('tab', {name: '写进程', exact: true}).getAttribute('aria-selected') === 'true', 'Process tabs support keyboard');
    }
    await page.locator('#writer-length').fill('');
    await page.getByRole('button', {name: '发起写入', exact: true}).click();
    check(await page.locator('#writer-status').textContent() === '尚未发起请求', 'Invalid request cannot mutate state');
    await page.locator('#writer-length').fill('8');
    await page.getByRole('button', {name: '发起写入', exact: true}).click();
    await page.getByRole('button', {name: '运行写进程', exact: true}).click();
    check(await page.locator('#occupancy').textContent() === '8 / 512 字节', 'Custom requests work');
  }
  const context = await page.context().browser().newContext({javaScriptEnabled: false});
  try {
    const fallback = await context.newPage();
    await fallback.goto(base + 'diagrams/ch7-pipe.html');
    check(await fallback.locator('#static-diagram').evaluate(el => el.open), 'No-script static fallback opens');
    check(await fallback.locator('#static-diagram img').evaluate(el => el.complete && el.naturalWidth > 0), 'No-script mechanism diagram loads');
    check(!(await fallback.locator('#controls').isVisible()), 'No-script fallback omits inactive controls');
  } finally { await context.close(); }
  await page.setViewportSize({width: 320, height: 740});
  await page.goto(base + 'diagrams/ch7-pipe.html');
  check(await page.locator('#ring').evaluate(el => el.getBoundingClientRect().top >= 0), 'Mobile shows buffer while operating');
  check(await page.getByRole('button', {name: '运行写进程', exact: true}).evaluate(el => el.getBoundingClientRect().bottom <= innerHeight), 'Mobile writer control fits with buffer without scrolling');
  await page.getByRole('tab', {name: '读进程', exact: true}).click();
  check(await page.getByRole('button', {name: '运行读进程', exact: true}).evaluate(el => el.getBoundingClientRect().bottom <= innerHeight), 'Mobile reader control fits in the same workspace');
}
