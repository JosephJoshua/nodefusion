async (page) => {
  await page.setViewportSize({width: 390, height: 844});
  await page.reload();
  await page.locator('.lesson-toolbar').getByRole('link', {name: '运行报告', exact: true}).click();
  const report = page.frameLocator('.study-panel iframe:not([hidden])');
  await report.locator('#app').waitFor({state: 'visible'});
  await report.locator('nav.tabs [data-tab=events]').click();
  await page.locator('.study-panel iframe:not([hidden])').evaluate(frame => {
    const win = frame.contentWindow;
    const run = win.eval('NF.runs[0]');
    const i = run.events.pc.findIndex(pc => run.source?.locations?.[
      '0x' + BigInt(pc).toString(16)]?.some(location => location.file != null));
    if (i < 0) throw new Error('Embedded report has no source');
    win.nfExport.gotoEvent(i);
  });
  await report.locator('#detail [data-view=source]').click();
  if (await report.locator('#detail .source-code').evaluate(node => node.clientHeight) < 80)
    throw new Error('Embedded mobile source viewport is too small');
  if (await report.locator('.left').evaluate(node => node.inert || node.clientHeight < 100))
    throw new Error('Embedded inspector hides the report navigator');
  await report.locator('#detail .source-code').focus();
  await page.keyboard.press('Escape');
  if (await report.locator('.right').isVisible()) throw new Error('First Escape did not close inspector');
  if (!(await page.locator('.study-panel').isVisible())) throw new Error('First Escape also closed report');
  await report.locator('#quick-query').focus();
  await page.keyboard.press('Escape');
  if (await page.locator('.study-panel').isVisible()) throw new Error('Second Escape did not return to chapter');
  return 'Embedded phone inspector preserves report and chapter navigation';
}
