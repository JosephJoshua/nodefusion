async (page) => {
  const check = (condition, label) => { if (!condition) throw new Error(label); };
  const base = await page.evaluate(() => new URL('./', location.href).href);
  await page.setViewportSize({width: 1440, height: 900});
  await page.goto(base + 'ch2/rcore.html');
  const sections = page.getByRole('combobox', {name: '跳转到小节', exact: true});
  await sections.selectOption('系统调用与返回');
  await page.getByRole('button', {name: '对照阅读', exact: true}).click();
  const pane = page.getByRole('complementary', {name: 'uCore 对照阅读'});
  await pane.getByRole('heading', {name: '系统调用与返回', exact: true}).waitFor();
  await page.getByRole('button', {name: '关闭对照阅读'}).click();
  await page.getByRole('link', {name: 'uCore', exact: true}).first().click();
  check(await page.getByRole('combobox', {name: '跳转到小节', exact: true}).inputValue() === '系统调用与返回', 'Chapter two implementation navigation keeps section');
  await page.getByRole('combobox', {name: '跳转到小节', exact: true}).selectOption('栈地址与上下文页');
  await page.getByRole('button', {name: '对照阅读', exact: true}).click();
  await page.getByRole('complementary', {name: 'rCore 对照阅读'}).getByRole('heading', {name: '异常入口与上下文', exact: true}).waitFor();
  await page.getByRole('button', {name: '关闭对照阅读'}).click();
  await page.getByRole('combobox', {name: '跳转到小节', exact: true}).selectOption('运行观察');
  const reading = await page.evaluate(() => window.scrollY);
  for (const [label, run, outcome] of [['原参考构建报告', 'ucore-2026A-ch2-reference', 'timeout'],
                                    ['栈地址修正版报告', 'ucore-2026A-ch2-stack-fixed', 'completed'],
                                    ['异常批次报告', 'ucore-2026A-ch2-faults', 'completed']]) {
    await page.getByRole('link', {name: label, exact: true}).click();
    const active = page.locator('.study-panel iframe:not([hidden])');
    check((await active.getAttribute('src')).includes(run + '.html'), 'Open explicitly selected build');
    const report = page.frameLocator(`iframe[src*="${run}.html"]`);
    await report.locator('#panel-functions.on').waitFor();
    check(await active.evaluate(frame => frame.contentWindow.nfExport.info().outcome) === outcome, 'Report outcome matches original or correction');
    await page.getByRole('button', {name: '返回正文', exact: true}).click();
    check(Math.abs(await page.evaluate(() => window.scrollY) - reading) < 2, 'Evidence view preserves reading offset');
  }
  await page.setViewportSize({width: 320, height: 740});
  await page.getByRole('combobox', {name: '跳转到小节', exact: true}).selectOption('栈地址与上下文页');
  check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'Stack explanation fits narrow screen');
  await page.getByRole('link', {name: 'rCore', exact: true}).first().click();
  check(await page.getByRole('combobox', {name: '跳转到小节', exact: true}).inputValue() === '异常入口与上下文', 'Stack case links to matching Rust mechanism');
  await page.goto(base + 'ch2/index.html');
  await page.getByRole('img', {name: '应用装载、系统调用与批次推进'}).waitFor();
  check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'Batch diagram fits narrow guide');
}
