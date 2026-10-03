async page => {
  const check = (condition, label) => { if (!condition) throw new Error(label); };
  const base = await page.evaluate(() => new URL('./', location.href).href);
  const sectionControl = {
    async selectOption(value) {
      const headings = page.locator('main > h2[id]');
      const id = typeof value === 'string' ? value : value.label || await headings.nth(value.index).getAttribute('id');
      await page.waitForFunction(() => Math.abs(parseFloat(document.querySelector('main').style.getPropertyValue('--lesson-offset')) - document.querySelector('.lesson-toolbar').getBoundingClientRect().height - 70) < 1);
      await page.evaluate(id => {
        const heading = document.getElementById(id);
        if (!heading) throw new Error('Missing section: ' + id);
        location.hash = encodeURIComponent(id);
        heading.scrollIntoView({block: 'start'});
        window.dispatchEvent(new HashChangeEvent('hashchange'));
      }, id);
      await page.waitForFunction(id => document.querySelector('.lesson-outline [aria-current="location"]')?.dataset.section === id, id);
    },
    inputValue: () => page.locator('.lesson-outline [aria-current="location"]').getAttribute('data-section'),
    locator: () => page.locator('main > h2[id]')
  };
  await page.evaluate(() => {
    sessionStorage.removeItem('nodefusion-study-side');
  });
  for (const width of [320, 390, 900, 1440]) {
    await page.setViewportSize({width, height: 740});
    for (const kernel of ['rcore', 'ucore']) {
      await page.goto(base + `ch7/${kernel}.html`);
      const select = sectionControl;
      check(await select.locator('option').count() === 7, 'Both implementations have seven matching sections');
      check(await page.locator('main > h2:visible').count() === 7, 'All sections are available for continuous reading');
      await select.selectOption('读写与调度');
      const heading = page.locator('main > h2[id="读写与调度"]');
      const top = await heading.evaluate(el => el.getBoundingClientRect().top);
      await page.locator('.lesson-toolbar').getByRole('link', {name: '交互图', exact: true}).click();
      const frame = page.frameLocator('.study-panel iframe:not([hidden])');
      await frame.locator('html.embedded-diagram').waitFor();
      check(await frame.getByRole('combobox', {name: '内核', exact: true}).inputValue() === kernel, 'Diagram opens the current implementation');
      check(!(await frame.locator('#return-to-lesson').isVisible()), 'Embedded diagram uses the persistent parent return control');
      if (width <= 390) {
        check(await frame.locator('#buffer-circle').evaluate(el => el.getBoundingClientRect().top >= 0), 'Buffer remains visible while operating');
        check(await frame.getByRole('button', {name: '运行写进程', exact: true}).evaluate(el => el.getBoundingClientRect().bottom <= innerHeight), `Embedded writer fits at ${width}px`);
      }
      await frame.getByRole('button', {name: '运行写进程', exact: true}).click();
      const capacity = kernel === 'rcore' ? 32 : 512;
      check(await frame.locator('#occupancy').textContent() === `${capacity} / ${capacity} 字节`, 'Writer fills the selected kernel buffer');
      const readerTab = frame.getByRole('tab', {name: '读进程', exact: true});
      if (await readerTab.isVisible()) await readerTab.click();
      if (width <= 390) {
        check(await frame.getByRole('button', {name: '运行读进程', exact: true}).evaluate(el => el.getBoundingClientRect().bottom <= innerHeight), 'Embedded reader fits with buffer visible');
      }
      const actionTop = await frame.locator('#reader-run').evaluate(el => el.getBoundingClientRect().top);
      await frame.getByRole('button', {name: '运行读进程', exact: true}).click();
      check(await frame.locator('#occupancy').textContent() === `0 / ${capacity} 字节`, 'Reader consumes the available bytes');
      check(Math.abs(await frame.locator('#reader-run').evaluate(el => el.getBoundingClientRect().top) - actionTop) < 1, 'Progress updates preserve the reader action position');
      check(await frame.locator('#read-index-label').textContent() === `${kernel === 'rcore' ? 'head' : '读下标'} = 0`, 'Diagram labels show the actual wrapped read index');
      await page.getByRole('button', {name: '返回正文', exact: true}).click();
      check(await select.inputValue() === '读写与调度', 'Return preserves the selected mechanism');
      const returnedTop = await heading.evaluate(el => el.getBoundingClientRect().top);
      check(Math.abs(returnedTop - top) < 3, `Return preserves reading position at ${width}px in ${kernel}: ${top} -> ${returnedTop}`);
      await page.locator('.lesson-toolbar').getByRole('link', {name: '交互图', exact: true}).click();
      check(await frame.locator('#occupancy').textContent() === `0 / ${capacity} 字节`, 'Reopening preserves the experiment');
      await page.getByRole('button', {name: '返回正文', exact: true}).click();
      await page.locator('.lesson-toolbar').getByRole('link', {name: '运行报告', exact: true}).click();
      await frame.locator('#panel-functions.on').waitFor();
      check(await page.getByRole('combobox', {name: '切换运行报告', exact: true}).locator('option').count() === (kernel === 'rcore' ? 4 : 2), 'Chapter workloads are available without finding links in the text');
      const query = kernel === 'rcore' ? 'write_byte' : 'pipewrite';
      await frame.locator('#function-search').fill(query);
      await page.getByRole('button', {name: '返回正文', exact: true}).click();
      await page.locator('.lesson-toolbar').getByRole('link', {name: '运行报告', exact: true}).click();
      check(await frame.locator('#function-search').inputValue() === query, 'Returning to a report keeps the actual function filter');
      await page.getByRole('button', {name: '返回正文', exact: true}).click();
      check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `Chapter fits ${width}px`);
      const counterpart = kernel === 'rcore' ? 'uCore' : 'rCore';
      await page.locator('.lesson-toolbar').getByRole('link', {name: counterpart, exact: true}).click();
      check(await select.inputValue() === '读写与调度', 'Implementation switch keeps the matching section');
    }
  }
  const response = await page.request.get(base + 'ch7/nfpipe_probe.c');
  check(response.ok() && (await response.text()).includes('int main('), 'The compiled independent experiment source is accessible');
}
