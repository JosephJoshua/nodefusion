async (page) => {
  await page.setViewportSize({width: 1440, height: 900});
  await page.reload();
  await page.locator('#app').waitFor({state: 'visible'});
  const toggle = page.locator('#toggle-nav');
  if (await toggle.getAttribute('aria-expanded') === 'false') await toggle.click();
  await page.locator('nav.tabs [data-tab=functions]').click();
  await page.locator('.sequence-node').first().click();
  const checkToolbar = async () => {
    const valid = await page.locator('.trace-controls').evaluate(toolbar => {
      const bounds = toolbar.getBoundingClientRect();
      const children = [...toolbar.children].map(node => node.getBoundingClientRect());
      return children.every(rect => rect.left >= bounds.left - 1 && rect.right <= bounds.right + 1)
        && children.every((rect, i) => children.every((other, j) => i === j
          || rect.right <= other.left || other.right <= rect.left
          || rect.bottom <= other.top || other.bottom <= rect.top));
    });
    if (!valid) throw new Error('Function controls clip or overlap');
  };
  await checkToolbar();
  await toggle.click();
  if (await page.locator('nav.tabs').evaluate(nav => nav.clientWidth) > 60)
    throw new Error('Collapsed navigation is not compact');
  await page.locator('nav.tabs [data-tab=events]').focus();
  await page.locator('.nav-tooltip').waitFor({state: 'visible'});
  if (await page.locator('.nav-tooltip').innerText() !== '事件')
    throw new Error('Collapsed navigation has no readable keyboard label');
  await page.reload();
  await page.locator('#app').waitFor({state: 'visible'});
  if (await toggle.getAttribute('aria-expanded') !== 'false')
    throw new Error('Navigation preference was lost');
  await page.locator('nav.tabs [data-tab=functions]').click();
  await page.locator('.sequence-node').first().click();
  await checkToolbar();
  await page.setViewportSize({width: 390, height: 844});
  await checkToolbar();
  if (await toggle.isVisible()) throw new Error('Desktop collapse control appears on mobile');
  if (!(await page.locator('nav.tabs [data-tab=events] .nav-label').isVisible()))
    throw new Error('Mobile navigation lost its labels');
  await page.setViewportSize({width: 1024, height: 720});
  await toggle.click();
  await checkToolbar();
  return 'Spacing, toolbar bounds, and collapsible navigation passed';
}
