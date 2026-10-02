(function () {
  'use strict';
  if (!['http:', 'https:'].includes(location.protocol)) return;
  const page = location.pathname.split('/').pop();
  if (['print.html', '404.html'].includes(page)) return;
  const main = document.querySelector('.content main');
  if (!main || document.getElementById('page-comments')) return;

  const section = document.createElement('section');
  section.id = 'page-comments';
  section.className = 'page-comments';
  section.setAttribute('aria-labelledby', 'comments-title');
  const title = document.createElement('h2');
  title.id = 'comments-title'; title.textContent = '评论';
  const host = document.createElement('div'); host.className = 'giscus';
  const fallback = document.createElement('a');
  fallback.href = 'https://github.com/LearningOS/nodefusion/discussions';
  fallback.textContent = '在 GitHub 上讨论';
  fallback.className = 'comments-fallback';
  section.append(title, host, fallback); main.append(section);

  const theme = () => ['coal', 'navy', 'ayu'].some(name => document.documentElement.classList.contains(name)) ? 'dark' : 'light';
  const script = document.createElement('script');
  script.src = 'https://giscus.app/client.js';
  script.async = true; script.crossOrigin = 'anonymous';
  const attributes = {
    repo: 'LearningOS/nodefusion',
    'repo-id': 'R_kgDOUTF6oQ',
    category: 'Announcements',
    'category-id': 'DIC_kwDOUTF6oc4DG3XB',
    mapping: 'specific',
    term: 'nodefusion/' + location.pathname.replace(/^\/nodefusion\//, '').replace(/^\//, '').replace(/\/$/, '/index.html').replace(/^$/, 'index.html'),
    strict: '1',
    'reactions-enabled': '0',
    'emit-metadata': '0',
    'input-position': 'top',
    theme: theme(),
    lang: 'zh-CN',
    loading: 'lazy',
  };
  for (const [key, value] of Object.entries(attributes)) script.setAttribute('data-' + key, value);
  host.append(script);
  let currentTheme = theme();
  new MutationObserver(() => {
    const next = theme();
    if (next === currentTheme) return;
    currentTheme = next;
    host.querySelector('iframe')?.contentWindow?.postMessage({giscus: {setConfig: {theme: next}}}, 'https://giscus.app');
  }).observe(document.documentElement, {attributes: true, attributeFilter: ['class']});
})();
