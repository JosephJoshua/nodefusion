async (page) => {
  const check = (value, message) => { if (!value) throw new Error(message); };
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  for (const width of [1440, 768, 390, 320]) {
    await page.setViewportSize({width, height: 844});
    await page.reload();
    await page.locator('#app').waitFor({state: 'visible'});
    await page.locator('nav.tabs [data-tab=functions]').click();
    const firstEntry = page.locator('.sequence-node').first();
    if (await firstEntry.count()) {
      await firstEntry.click();
      if (width <= 850) await page.locator('#close-mobile-detail').click();
    }
    await page.locator('nav.tabs [data-tab=events]').click();
    const result = await page.evaluate(() => {
      const run = NF.runs[0];
      const i = run.events.pc.findIndex(pc => run.source?.locations?.[hex(pc)]?.some(loc => loc.file != null && loc.line > 0));
      if (i < 0) return -1;
      window.nfExport.gotoEvent(i); return i;
    });
    check(result >= 0, 'Report has a recorded source location');
    await page.locator('#detail .detail-tabs [data-view=source]').click();
    check(await page.locator('nav.tabs button.on').getAttribute('data-tab') === 'events', 'Event context preserved');
    await page.locator('#detail .source-code').waitFor({state: 'visible'});
    await page.waitForFunction(() => {
      const code = document.querySelector('#detail .source-code');
      const line = code?.querySelector('.source-current');
      if (!line) return false;
      const viewport = code.getBoundingClientRect(), current = line.getBoundingClientRect();
      return current.top >= viewport.top && current.bottom <= viewport.bottom;
    });
    check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `No page overflow at ${width}`);
    const code = page.locator('#detail .source-code');
    check(await code.evaluate(node => node.clientHeight) >= 180, `Usable code viewport at ${width}`);
    if (width <= 850) {
      check(await page.locator('.right').evaluate(node => Math.abs(node.getBoundingClientRect().top) < 1 && node.clientHeight === innerHeight), 'Full-height mobile inspector');
      await page.locator('#detail .detail-tabs [data-view=stack]').click();
      check(await page.locator('#detail .debug-stack').isVisible(), 'Stack gets its own view');
      await page.locator('#detail .debug-frame').first().click();
      check(await code.isVisible(), 'Frame selection returns directly to source');
      await code.evaluate(node => { node.scrollTop = node.scrollHeight; });
      check(await page.locator('#close-mobile-detail').evaluate(node => node.getBoundingClientRect().top >= 0 && node.getBoundingClientRect().bottom < 70), 'Back stays visible after code scroll');
      await page.keyboard.press('Escape');
      check(!(await page.locator('.right').isVisible()), 'Escape returns to event list');
      check(!(await page.locator('.left').evaluate(node => node.inert)), 'List is usable after return');
    }
  }
  await page.setViewportSize({width: 844, height: 390});
  await page.reload();
  await page.locator('#app').waitFor({state: 'visible'});
  await page.locator('nav.tabs [data-tab=events]').click();
  await page.evaluate(() => {
    const run = NF.runs[0];
    window.nfExport.gotoEvent(run.events.pc.findIndex(pc =>
      run.source?.locations?.[hex(pc)]?.some(loc => loc.file != null)));
  });
  await page.locator('#detail .detail-tabs [data-view=source]').click();
  check(await page.locator('#detail .source-code').evaluate(node => node.clientHeight) >= 100,
    'Landscape phone has a usable code viewport');
  await page.locator('#detail .source-tools-toggle').click();
  check(await page.locator('#detail .source-controls').isVisible(), 'Landscape search is accessible');
  await page.locator('#detail .source-tools-toggle').click();
  check(!(await page.locator('#detail .source-controls').isVisible()), 'Landscape search can be dismissed');
  await page.keyboard.press('Escape');
  check(errors.length === 0, errors.join('\n'));
  return 'Inspector desktop, tablet, and phone workflows passed';
}
