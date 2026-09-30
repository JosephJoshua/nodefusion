async (page) => {
  const check = (condition, label) => { if (!condition) throw new Error(label); };
  const base = await page.evaluate(() => new URL('/', location.href).href);
  await page.setViewportSize({width: 390, height: 844});
  await page.goto(base + 'reports/rcore/ch8/2026a/rcore-2026A-ch8-basic-observed-v3.html?ui=' + Date.now());
  await page.locator('#app').waitFor({state: 'visible'});
  await page.getByRole('searchbox', {name: '搜索事件或函数'}).fill('mutex');
  await page.getByRole('search', {name: '查找运行记录'}).getByRole('button', {name: '查找'}).click();
  await page.locator('#panel-events.on').waitFor();
  check(await page.locator('nav.tabs button[data-tab="events"]').evaluate(el => {
    const item = el.getBoundingClientRect();
    const nav = el.parentElement.getBoundingClientRect();
    return item.left >= nav.left && item.right <= nav.right;
  }), 'Mobile navigation keeps the active view visible');
  check(await page.locator('#quick-query').inputValue() === 'mutex', 'Quick find keeps the active query visible');
  check(await page.locator('#event-search').count() === 0, 'Only one text search is shown');
  check(await page.locator('#evscroll tbody tr.clickable').count() > 0, 'Quick find finds matching events');
  check(await page.locator('#evscroll').evaluate(el => {
    const visible = [...el.querySelectorAll('th')].filter(th => getComputedStyle(th).display !== 'none');
    const eventCell = el.querySelector('tr.clickable td:nth-child(5)');
    return visible.length === 3 && eventCell.getBoundingClientRect().width >= 150 &&
      el.scrollWidth <= el.clientWidth + 1;
  }), 'Mobile results show three useful columns without horizontal scrolling');
  const resultCount = Number((await page.locator('.result-bar strong').innerText()).replace(/[^\d]/g, ''));
  const facetCount = await page.locator('.event-facets .facet').first().locator('b').innerText();
  check(Number(facetCount.replaceAll(',', '')) <= resultCount, 'Event type counts follow the current query');
  check(await page.locator('.result-bar').evaluate(el => {
    const rect = el.getBoundingClientRect();
    return rect.top >= 45 && rect.bottom < innerHeight;
  }), 'Mobile search moves the result count into view');
  check(await page.locator('#evscroll tbody tr.clickable').first().evaluate(el => {
    const rect = el.getBoundingClientRect();
    return rect.top >= 0 && rect.top < innerHeight;
  }), 'Mobile search makes the first matching event visible');
  check(await page.locator('#quick-query').evaluate(el => {
    const rect = el.getBoundingClientRect();
    return rect.top >= 0 && rect.bottom < 90;
  }), 'Mobile search stays available while reviewing results');
  await page.locator('#evscroll tbody tr.clickable').first().click();
  check(await page.locator('.right').isVisible(), 'Event detail opens on mobile');
  check((await page.locator('.result-position').innerText()).startsWith('1 /'), 'Selection position is visible');
  await page.locator('.result-nav button').last().click();
  check((await page.locator('.result-position').innerText()).startsWith('2 /'), 'Next result advances selection');
  await page.keyboard.press('k');
  check((await page.locator('.result-position').innerText()).startsWith('1 /'), 'K returns to the previous result');
  const scrollBeforeStep = await page.locator('#evscroll').evaluate(el => { el.scrollTop = 340; return el.scrollTop; });
  await page.getByRole('button', {name: '下一帧', exact: true}).click();
  check(Math.abs(await page.locator('#evscroll').evaluate(el => el.scrollTop) - scrollBeforeStep) < 2,
        'Changing the snapshot keeps the event list position');
  await page.getByRole('button', {name: '关闭详情'}).click();
  check(!(await page.locator('.right').isVisible()), 'Event detail closes on mobile');
  await page.getByRole('searchbox', {name: '搜索事件或函数'}).fill('pid:27');
  await page.getByRole('search', {name: '查找运行记录'}).getByRole('button', {name: '查找'}).click();
  check(await page.locator('#event-pid').inputValue() === '27', 'PID query applies the process filter');
  await page.getByRole('searchbox', {name: '搜索事件或函数'}).fill('#67,000,523');
  await page.getByRole('search', {name: '查找运行记录'}).getByRole('button', {name: '查找'}).click();
  check(await page.evaluate(() => NF.cur) === 67000523, 'Instruction query moves the timeline');

  await page.goto(base + 'reports/xv6/boot/boot-trace.html?ui=' + Date.now());
  await page.locator('#app').waitFor({state: 'visible'});
  await page.getByRole('button', {name: '函数轨迹'}).click();
  check((await page.locator('#panel-functions .section-subtitle').textContent()).includes('入口事件 6 条'),
        'Legacy bundle reports the recorded function entries');
}
