const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('site/theme/comments.js', 'utf8');

function render(pathname, protocol = 'https:') {
  const nodes = [];
  const make = tag => {
    const node = {tag, children: [], attributes: {},
      setAttribute(key, value) { this.attributes[key] = value; },
      append(...children) { this.children.push(...children); },
      querySelector() { return null; }};
    nodes.push(node); return node;
  };
  const main = make('main');
  const html = {classList: {contains: () => false}};
  const context = {location: {pathname, protocol},
    document: {documentElement: html,
      querySelector: () => main,
      getElementById: id => nodes.find(node => node.id === id),
      createElement: make},
    MutationObserver: class { observe() {} }};
  vm.runInNewContext(source, context);
  vm.runInNewContext(source, context);
  return {nodes, main};
}
for (const path of ['/nodefusion/', '/nodefusion/index.html']) {
  const {nodes, main} = render(path);
  assert.equal(main.children.length, 1, 'Only one section per page');
  const script = nodes.find(node => node.tag === 'script');
  assert.equal(script.attributes['data-term'], 'nodefusion/index.html');
  assert.equal(script.attributes['data-lang'], 'zh-CN');
  assert.equal(script.attributes['data-strict'], '1');
  assert.equal(script.attributes['data-loading'], 'lazy');
  assert.equal(script.src, 'https://giscus.app/client.js');
}
const chapter = render('/nodefusion/ch8/ucore.html').nodes.find(node => node.tag === 'script');
assert.equal(chapter.attributes['data-term'], 'nodefusion/ch8/ucore.html');
for (const [path, protocol] of [['/nodefusion/print.html', 'https:'], ['/nodefusion/404.html', 'https:'], ['/tmp/index.html', 'file:']])
  assert.equal(render(path, protocol).main.children.length, 0);
console.log('Comment mapping, configuration, duplicates, and offline/print exclusions passed');
