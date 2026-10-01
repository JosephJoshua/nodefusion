async page => {
  const check = (value, message) => { if (!value) throw new Error(message); };
  const base = await page.evaluate(() => new URL('./', location.href).href);
  const names = ['ch1-boot', 'ch2-batch', 'ch3-context', 'ch3-switch', 'ch4-sv39',
    'ch5-lifecycle', 'ch6-blocks', 'ch6-files', 'ch7-pipe', 'ch8-sync', 'ch8-threads'];
  await page.setViewportSize({width: 1440, height: 900});
  for (const name of names) {
    await page.goto(base + 'diagrams/' + name + '.svg');
    const errors = await page.evaluate(() => {
      const bounds = document.querySelector('svg').viewBox.baseVal;
      const texts = [...document.querySelectorAll('text')].map(element =>
        ({text: element.textContent, box: element.getBBox()}));
      const errors = texts.filter(({box}) => box.x < 0 || box.y < 0 ||
        box.x + box.width > bounds.width || box.y + box.height > bounds.height).map(item => item.text);
      for (let i = 0; i < texts.length; i++) {
        for (let j = i + 1; j < texts.length; j++) {
          const a = texts[i].box, b = texts[j].box;
          if (Math.min(a.x + a.width, b.x + b.width) - Math.max(a.x, b.x) > 1 &&
              Math.min(a.y + a.height, b.y + b.height) - Math.max(a.y, b.y) > 1)
            errors.push(texts[i].text + ' overlaps ' + texts[j].text);
        }
      }
      return errors;
    });
    check(!errors.length, name + ': ' + errors.join('; '));
  }
  for (const width of [320, 390, 1440]) {
    await page.setViewportSize({width, height: 740});
    for (const chapter of [1, 4, 6, 8]) {
      await page.goto(base + `ch${chapter}/index.html`);
      const link = page.locator('.figure-link').first();
      await link.scrollIntoViewIfNeeded();
      await link.focus();
      const readingY = await page.evaluate(() => scrollY);
      await page.keyboard.press('Enter');
      const viewer = page.getByRole('dialog', {name: '查看配图'});
      await viewer.waitFor();
      await viewer.locator('img').evaluate(image => image.decode());
      check(await viewer.evaluate(element => {
        const rect = element.getBoundingClientRect();
        return rect.left >= 0 && rect.right <= innerWidth && rect.top >= 0 && rect.bottom <= innerHeight;
      }), `Viewer fits ${width}px in chapter ${chapter}`);
      await viewer.getByRole('button', {name: '100%', exact: true}).click();
      check(await viewer.locator('output').textContent() === '100%', '100% uses vector image dimensions');
      await page.keyboard.press('+');
      check(await viewer.locator('output').textContent() === '125%', 'Keyboard zoom enlarges figure');
      await viewer.getByRole('button', {name: '适应窗口', exact: true}).click();
      check(await viewer.locator('.figure-viewport').evaluate(element =>
        element.scrollWidth <= element.clientWidth && element.scrollHeight <= element.clientHeight), 'Fit shows the whole diagram');
      await page.keyboard.press('Escape');
      check(!(await viewer.isVisible()), 'Escape closes the viewer');
      check(await link.evaluate(element => document.activeElement === element), 'Closing returns focus to the figure');
      check(Math.abs(await page.evaluate(() => scrollY) - readingY) < 2, 'Closing preserves reading position');
      check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'Page has no horizontal overflow');
    }
  }
  const context = await page.context().browser().newContext({javaScriptEnabled: false});
  try {
    const fallback = await context.newPage();
    await fallback.goto(base + 'ch4/index.html');
    const [figure] = await Promise.all([
      context.waitForEvent('page'),
      fallback.locator('main a:has(> img)').click()
    ]);
    await figure.waitForURL('**/diagrams/ch4-sv39.svg');
    check(await figure.locator('svg').count() === 1, 'Without JavaScript the linked SVG opens directly');
  } finally { await context.close(); }
}
