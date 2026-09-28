async (page) => {
  const check = (condition, label) => { if (!condition) throw new Error(label); };
  const base = await page.evaluate(() => new URL('./', location.href).href);
  const standalone = await page.context().newPage();
  try {
    await standalone.route('**/ucore-2026A-ch4-pagetable.html?*', async route => {
      const response = await route.fetch();
      const html = await response.text();
      let replaced = 0;
      const body = html.replace(/<script>([\s\S]*?)<\/script>/g, (tag, script) => {
        if (!script.includes('const NF =')) return tag;
        replaced++;
        return '';
      });
      check(replaced === 1, 'Use the real report bundle with only its old UI script removed');
      await route.fulfill({response, body});
    });
    await standalone.setViewportSize({width: 1440, height: 900});
    await standalone.goto(base + 'reports/ucoreos/ch4/2026a/ucore-2026A-ch4-pagetable.html?tab=functions');
    await standalone.addScriptTag({path: 'nodefusion/host/assets/app.js'});
    await standalone.addStyleTag({path: 'nodefusion/host/assets/app.css'});
    await standalone.evaluate(() => boot());
    await standalone.locator('#panel-functions.on').waitFor();
    await standalone.locator('#function-search').fill('uvmunmap');
    await standalone.locator('#function-cpu').selectOption('0');
    await standalone.locator('#function-limit').selectOption('40');
    await standalone.locator('#function-grouping').selectOption('caller');
    await standalone.setViewportSize({width: 1440, height: 600});
    await standalone.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    check(await standalone.locator('#panel-functions').evaluate(panel => { panel.scrollTop = 100; return panel.scrollTop > 0; }), 'Exercise an actually scrolled results panel');
    check(await standalone.locator('.trace-controls').evaluate(el => {
      const panel = el.closest('.panel').getBoundingClientRect();
      const bounds = el.getBoundingClientRect();
      return bounds.top >= panel.top - 1 && bounds.bottom <= panel.bottom;
    }), 'Function filters remain visible while scrolling results');
    await standalone.getByRole('button', {name: '上一帧', exact: true}).click();
    await standalone.setViewportSize({width: 390, height: 844});
    await standalone.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    check(await standalone.locator('#function-search').inputValue() === 'uvmunmap', 'Standalone redraw retains search');
    check(await standalone.locator('#function-cpu').inputValue() === '0', 'Standalone redraw retains CPU');
    check(await standalone.locator('#function-limit').inputValue() === '40', 'Standalone redraw retains limit');
    check(await standalone.locator('#function-grouping').inputValue() === 'caller', 'Standalone redraw retains grouping');
    await standalone.getByRole('button', {name: '事件', exact: true}).click();
    await standalone.getByRole('button', {name: '函数轨迹', exact: true}).click();
    check(await standalone.locator('#function-search').inputValue() === 'uvmunmap', 'Switching report views retains search');
    check(await standalone.locator('.sequence-function').count() > 0, 'Real matching entries are still displayed');
    check(await standalone.locator('.trace-panel').first().evaluate(el => el.getBoundingClientRect().height < 200), 'Small filtered result uses its content height on mobile');
  } finally {
    await standalone.close();
  }
}
