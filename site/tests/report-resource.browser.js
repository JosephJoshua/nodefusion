async (page) => {
  await page.setViewportSize({width: 390, height: 844});
  await page.reload();
  await page.locator('#app').waitFor({state: 'visible'});
  const time = await page.evaluate(() => {
    const run = NF.runs[0];
    const state = [...run.states].reverse().find(state => state.procs.some(proc =>
      run.events.pid.some((pid, i) => pid === proc.pid && run.events.insn[i] <= state.insn)));
    if (!state) throw new Error('Report has no process with preceding events');
    const proc = state.procs.find(proc => run.events.pid.some((pid, i) =>
      pid === proc.pid && run.events.insn[i] <= state.insn));
    NF.cur = state.insn;
    setTab('procs');
    showProcDetail(run, state, proc);
    return NF.cur;
  });
  await page.locator('#detail .related-event').first().click();
  if (await page.locator('#close-mobile-detail').textContent() !== '返回进程')
    throw new Error('Resource return action is missing');
  await page.locator('#detail [data-view=source]').click();
  await page.locator('#close-mobile-detail').click();
  if (await page.evaluate(() => NF.cur) !== time) throw new Error('Resource time was lost');
  if (await page.locator('#detail .detail-tabs').count()) throw new Error('Resource detail was not restored');
  await page.keyboard.press('Escape');
  if (await page.locator('.right').isVisible()) throw new Error('Resource inspector did not close');
  if (await page.locator('.left').evaluate(node => node.inert)) throw new Error('Process list is still inert');
  return 'Process → event → source → process → list passed';
}
