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
      await page.locator('nav.tabs button[data-tab="events"]').click();
      await page.locator('#panel-events.on').waitFor();
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
  if (catalog.reports.length !== 55) throw new Error(`Expected 55 reports, found ${catalog.reports.length}`);
}
