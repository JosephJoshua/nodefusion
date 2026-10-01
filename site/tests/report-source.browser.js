async (page) => {
  const check = (value, message) => { if (!value) throw new Error(message); };
  const errors = [];
  const external = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => {
    if (/^https?:/.test(request.url()) && new URL(request.url()).origin !== new URL(page.url()).origin)
      external.push(request.url());
  });
  await page.setViewportSize({width: 1440, height: 900});
  await page.reload();
  await page.locator('#app').waitFor({state: 'visible'});
  await page.getByRole('button', {name: '函数轨迹', exact: true}).click();
  await page.locator('.sequence-node').last().click();
  await page.locator('.debugger').waitFor();
  const frames = page.getByRole('listbox', {name: '选择栈帧'});
  check(await frames.getByRole('option').count() === 2, 'Nested stack has two frames');
  check(await page.locator('.debug-symbol').textContent() === 'child', 'Current frame selected first');
  check(await page.locator('.source-code .hljs-keyword').count() > 0, 'C source syntax highlighted');
  await frames.getByRole('option').first().focus();
  await page.keyboard.press('ArrowDown');
  check(await page.locator('.debug-symbol').textContent() === 'root', 'Arrow key selects parent source');
  check(await frames.getByRole('option').last().getAttribute('aria-selected') === 'true', 'Selected frame announced');
  await page.setViewportSize({width: 1200, height: 900});
  check(await page.locator('.debug-symbol').textContent() === 'root', 'Resize preserves selected parent frame');
  await page.setViewportSize({width: 1440, height: 900});
  const time = await page.locator('#tlabel').textContent();
  await page.locator('.source-code').focus(); await page.keyboard.press('ArrowRight');
  check(await page.locator('#tlabel').textContent() === time, 'Code navigation does not step the timeline');
  check(await page.locator('.source-current').count() === 1, 'Source highlights mapped call site');
  await page.getByRole('searchbox', {name: '在源码文件中查找'}).fill('return');
  await page.getByRole('button', {name: '下一个', exact: true}).click();
  check(await page.locator('.source-match').count() === 1, 'File search selects a match');
  await page.getByRole('spinbutton', {name: '跳转到行'}).fill('7');
  await page.keyboard.press('Enter');
  check(await page.locator('.source-line[data-line="7"]').count() === 1, 'Go to line renders requested line');
  const sourceTop = await page.locator('.source-code').evaluate(node => node.scrollTop);
  await frames.getByRole('option').first().click();
  await frames.getByRole('option').last().click();
  check(await page.getByRole('searchbox', {name: '在源码文件中查找'}).inputValue() === 'return', 'Returning to a frame preserves file search');
  check(await page.locator('.source-code').evaluate(node => node.scrollTop) === sourceTop, 'Returning to a frame preserves code scroll');
  const splitter = page.getByRole('separator', {name: '调整调用栈大小'});
  const horizontal = await splitter.getAttribute('aria-orientation') === 'horizontal';
  const initial = await page.locator('.debug-stack').evaluate((el, horizontal) => horizontal ? el.clientHeight : el.clientWidth, horizontal);
  await splitter.focus(); await page.keyboard.press(horizontal ? 'ArrowDown' : 'ArrowRight');
  check(await page.locator('.debug-stack').evaluate((el, horizontal) => horizontal ? el.clientHeight : el.clientWidth, horizontal) > initial, 'Keyboard resizes call stack');
  await page.getByRole('button', {name: '上一事件', exact: true}).click();
  check(await frames.getByRole('option').count() === 1, 'Event navigation changes stack');
  await page.locator('#function-search').fill('missing-function');
  check(await page.locator('.sequence-node').count() === 0, 'Filter has no stale entries');
  check(await page.locator('.debug-symbol').textContent() === 'root', 'Filtering preserves the inspected event');
  check(await page.getByRole('button', {name: '下一事件', exact: true}).isDisabled(), 'Navigation respects the current filter');
  await page.locator('#function-search').fill('');
  for (const width of [390, 768, 1440]) {
    await page.setViewportSize({width, height: 900});
    check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `No page overflow at ${width}`);
    if (width <= 850) {
      await page.locator('.sequence-node').first().click();
      check(await page.locator('#detail .debugger').isVisible(), `Selection opens inspector at ${width}`);
      await page.locator('#close-mobile-detail').click();
    } else { await page.locator('.sequence-node').first().click(); check(await page.locator('.detail-debugger').isVisible(), `Source pane visible at ${width}`); }
  }
  check(errors.length === 0, errors.join('\n'));
  check(external.length === 0, 'Source viewer requires no external requests');
  check(await page.evaluate(() => JSON.stringify(functionParts('kernel::Type<fn() -> other::Value>::run')) ===
    JSON.stringify(['kernel', 'Type<fn() -> other::Value>', 'run'])), 'Namespace tree preserves generic types');
  check(await page.evaluate(() => {
    const run = {format:'nodefusion.bundle/2', dict:{funcs:['_Ropaque'], raw_funcs:['_Ropaque'], full_funcs:['core::slice::sort::<T>']}};
    prepareBundle(run);
    return run.dict.funcs[0] === 'core::slice::sort::<T>' && run.dict.raw_funcs[0] === '_Ropaque' &&
      kindName(run, 'func._Ropaque') === 'func.core::slice::sort::<T>';
  }), 'Readable full names replace unresolved short names without changing identity');
}
