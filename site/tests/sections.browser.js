async (page) => {
  const check = (condition, label) => { if (!condition) throw new Error(label); };
  const base = await page.evaluate(() => new URL('./', location.href).href);
  for (const width of [320, 390, 900, 1440]) {
    await page.setViewportSize({width, height: 900});
    await page.goto(base + 'ch4/rcore.html');
    check(await page.locator('main > h2:visible').count() === 6, 'All six sections remain in the reading page');
    check(await page.getByRole('button', {name: '逐节阅读', exact: true}).count() === 0, 'No reading mode control');
    check(await page.getByRole('combobox', {name: '跳转到小节', exact: true}).count() === 0, 'No top section selector');
    await page.evaluate(() => { location.hash = encodeURIComponent('用户地址检查'); });
    await page.waitForFunction(() => document.querySelector('.lesson-outline [aria-current="location"]')?.dataset.section === '用户地址检查');
    check(await page.locator('main > h2[id="用户地址检查"]').isVisible(), 'Fragment reaches the section');
    check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'Lesson fits ' + width + 'px');
    await page.reload();
    check(await page.locator('main > h2:visible').count() === 6, 'Reload retains continuous reading');
  }
  await page.setViewportSize({width: 1440, height: 900});
  await page.goto(base + 'ch3/rcore.html#让出与选择下一个任务');
  await page.getByRole('link', {name: 'uCore', exact: true}).first().click();
  check(decodeURIComponent(new URL(page.url()).hash) === '#让出处理器', 'Counterpart opens the matching mechanism');
  await page.getByRole('button', {name: '对照阅读', exact: true}).click();
  await page.getByRole('complementary', {name: 'rCore 对照阅读'}).getByRole('heading', {name: '让出与选择下一个任务', exact: true}).waitFor();
  await page.getByRole('button', {name: '关闭对照阅读'}).click();
  await page.emulateMedia({media: 'print'});
  check(await page.locator('main > h2:visible').count() > 1, 'Printing includes the full chapter');
  await page.emulateMedia({media: 'screen'});
  const noScript = await page.context().browser().newContext({javaScriptEnabled: false});
  const fallback = await noScript.newPage();
  await fallback.goto(base + 'ch4/rcore.html');
  check(await fallback.locator('main > h2:visible').count() === 6, 'The chapter is readable without scripts');
  await noScript.close();
}
