(function () {
  'use strict';
  const sidebar = document.getElementById('mdbook-sidebar');
  const toggle = document.getElementById('mdbook-sidebar-toggle-anchor');
  const button = document.getElementById('mdbook-sidebar-toggle');
  if (!sidebar || !toggle || !button) return;
  button.setAttribute('role', 'button');
  button.tabIndex = 0;
  button.title = '目录';
  button.setAttribute('aria-label', '目录');
  button.addEventListener('keydown', event => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      button.click();
    }
  });
  for (const [id, title] of [['mdbook-theme-toggle', '主题'], ['mdbook-search-toggle', '搜索正文']]) {
    const control = document.getElementById(id);
    if (control) {
      control.title = title;
      control.setAttribute('aria-label', title);
    }
  }
  for (const [selector, title] of [['#mdbook-menu-bar a[href$="print.html"]', '打印全书'], ['#mdbook-menu-bar a[href^="https://github.com/"]', '项目源码']]) {
    const link = document.querySelector(selector);
    if (link) {
      link.title = title;
      link.setAttribute('aria-label', title);
    }
  }
  const narrow = window.matchMedia('(max-width: 900px)');
  const backdrop = document.createElement('button');
  backdrop.className = 'sidebar-backdrop';
  backdrop.type = 'button';
  backdrop.tabIndex = -1;
  backdrop.setAttribute('aria-label', '关闭目录');
  document.body.append(backdrop);
  function close(returnFocus) {
    if (!toggle.checked) return;
    toggle.checked = false;
    toggle.dispatchEvent(new Event('change'));
    backdrop.hidden = true;
    if (returnFocus) button.focus();
  }
  function update() {
    backdrop.hidden = !narrow.matches || !toggle.checked;
  }
  function resize() {
    if (narrow.matches) close(false);
    update();
  }
  backdrop.addEventListener('click', () => close(true));
  toggle.addEventListener('change', update);
  narrow.addEventListener('change', resize);
  window.addEventListener('keydown', event => {
    if (event.key === 'Escape' && narrow.matches && toggle.checked) {
      close(true);
      event.preventDefault();
    }
  });
  sidebar.addEventListener('click', event => {
    if (narrow.matches && event.target.closest('a[href]')) close(false);
  });
  resize();
})();
