async (page) => {
  const base = await page.evaluate(() => new URL('/', location.href).href);
  const catalog = await (await page.request.get(base + 'reports/index.json')).json();
  const failures = [];
  let current = '';
  page.on('pageerror', error => failures.push(`${current}: ${error.message}`));
  for (const report of catalog.reports) {
    current = report.path;
    await page.goto(base + 'reports/' + report.path + '?ui=' + Date.now(), {waitUntil: 'domcontentloaded'});
    try {
      await page.locator('#app').waitFor({state: 'visible', timeout: 20000});
      await page.locator('#quick-query').waitFor({state: 'visible'});
      await page.locator('nav.tabs button[data-tab="functions"]').click();
      await page.locator('#panel-functions.on').waitFor();
      const entry = page.locator('.sequence-node').first();
      if (await entry.count()) {
        await entry.click();
        if (await page.evaluate(() => innerWidth <= 850))
          await page.locator('#close-mobile-detail').click();
      }
      await page.locator('nav.tabs button[data-tab="events"]').click();
      await page.locator('#panel-events.on').waitFor();
      const sourceEvent = await page.evaluate(() => {
        if (NF.runs.some(run => !run.source?.files?.length)) return -1;
        const run = NF.runs[0];
        const index = run.events.pc.findIndex(pc => run.source.locations[hex(pc)]?.some(
          location => location.file != null && location.line > 0));
        if (index >= 0) window.nfExport.gotoEvent(index);
        return index;
      });
      if (sourceEvent < 0) throw new Error('No recorded event with embedded source');
      await page.locator('#detail .detail-tabs [data-view="source"]').click();
      await page.locator('#detail .source-code').waitFor({state: 'visible'});
      if (await page.evaluate(() => innerWidth <= 850))
        await page.locator('#close-mobile-detail').click();
      if (await page.locator('#panel-events .result-nav').count() !== 1)
        failures.push(`${current}: event navigation missing`);
      if (await page.locator('#event-search').count() !== 0)
        failures.push(`${current}: duplicate search input`);
      const info = await page.evaluate(() => window.nfExport?.info());
      if (!info || !info.outcome) failures.push(`${current}: report did not expose run information`);
    } catch (error) {
      failures.push(`${current}: ${error.message}`);
    }
  }
  if (failures.length) throw new Error(failures.join('\n'));
  if (catalog.reports.length !== 39) throw new Error(`Expected 39 reports, found ${catalog.reports.length}`);
}
