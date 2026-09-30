async (page) => {
  const base = await page.evaluate(() => new URL('/', location.href).href);
  const chapters = Array.from({length: 8}, (_, index) => index + 1);
  const paths = ['', 'reports.html', ...chapters.flatMap(chapter =>
    ['index', 'rcore', 'ucore'].map(page => `ch${chapter}/${page}.html`))];
  const failures = [];
  page.on('pageerror', error => failures.push(`${page.url()}: ${error.message}`));
  for (const width of [320, 390, 1440]) {
    await page.setViewportSize({width, height: 900});
    for (const path of paths) {
      await page.goto(base + path);
      const state = await page.evaluate(() => ({
        heading: !!document.querySelector('main h1'),
        overflow: document.documentElement.scrollWidth > innerWidth,
        brokenImages: [...document.querySelectorAll('main img')].filter(image =>
          !image.complete || !image.naturalWidth).length
      }));
      if (!state.heading || state.overflow || state.brokenImages)
        failures.push(`${width}px ${path || 'index.html'}: ${JSON.stringify(state)}`);
    }
  }
  if (failures.length) throw new Error(failures.join('\n'));
}
