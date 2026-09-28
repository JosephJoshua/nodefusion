const assert = require('node:assert/strict');
const {create, unread, pending, start, close, run, preset} = require('../src/diagrams/pipe.js');
let cases = 0;
function checked(state) {
  assert.ok(unread(state) >= 0 && unread(state) <= state.capacity);
  return state;
}
for (const kernel of ['rcore', 'ucore']) {
  const state = create(kernel);
  start(state, 'writer', 3000);
  let received = [];
  while (pending(state.writer) || unread(state)) {
    if (pending(state.writer)) run(checked(state), 'writer');
    if (!pending(state.reader)) start(state, 'reader', kernel === 'rcore' ? 3000 : 137);
    run(checked(state), 'reader');
    if (state.reader.result !== null) received.push(...state.reader.values);
  }
  assert.equal(state.writer.result, 3000);
  close(state, 'writer');
  if (pending(state.reader)) { run(state, 'reader'); received.push(...state.reader.values); }
  assert.deepEqual(received, Array.from({length: 3000}, (_, i) => i % 256));
  start(state, 'reader', 1);
  assert.equal(run(state, 'reader').result, kernel === 'rcore' ? 0 : -1);
  close(state, 'reader');
  assert.equal(state.released, true);
  cases++;

  const short = preset(kernel, 'short');
  const read = run(short, 'reader');
  assert.equal(short.reader.done, 5);
  assert.equal(read.kind, kernel === 'rcore' ? 'yield' : 'return');
  assert.equal(short.reader.result, kernel === 'rcore' ? null : 5);
  close(short, 'writer');
  if (pending(short.reader)) assert.equal(run(short, 'reader').result, 5);
  cases++;

  const wrap = preset(kernel, 'wrap');
  const write = run(wrap, 'writer');
  assert.equal(write.result, 12);
  assert.equal(wrap.writeCount % wrap.capacity, 8);
  assert.equal(unread(wrap), 16);
  if (kernel === 'ucore') assert.deepEqual(write.chunks.map(c => c.count), [4, 8]);
  start(wrap, 'reader', 16);
  run(wrap, 'reader');
  assert.equal(unread(wrap), 0);
  assert.deepEqual(wrap.reader.values, [wrap.capacity - 8, wrap.capacity - 7, wrap.capacity - 6, wrap.capacity - 5].map(n => n % 256).concat(Array.from({length: 12}, (_, i) => i)));
  cases++;

  const closed = preset(kernel, 'closed');
  const broken = run(closed, 'writer');
  assert.equal(broken.kind, kernel === 'rcore' ? 'yield' : 'return');
  assert.equal(closed.writer.result, kernel === 'rcore' ? null : -1);
  assert.equal(unread(closed), kernel === 'rcore' ? 32 : 0);
  cases++;

  for (const actor of ['writer', 'reader']) {
    const zero = create(kernel);
    start(zero, actor, 0);
    assert.equal(run(zero, actor).kind, kernel === 'rcore' ? 'return' : 'panic');
    assert.equal(unread(zero), 0);
    cases++;
  }
  const wait = create(kernel);
  start(wait, 'reader', 10);
  assert.equal(run(wait, 'reader').kind, 'yield');
  assert.throws(() => close(wait, 'reader'));
  assert.throws(() => start(wait, 'reader', 1));
  close(wait, 'writer');
  assert.equal(run(wait, 'reader').result, kernel === 'rcore' ? 0 : -1);
  cases++;
}
const overflow = create('ucore');
overflow.readCount = overflow.writeCount = 0xfffffff0;
start(overflow, 'writer', 32); run(overflow, 'writer');
assert.equal(overflow.writeCount, 16); assert.equal(unread(overflow), 32);
start(overflow, 'reader', 32); run(overflow, 'reader');
assert.equal(overflow.readCount, 16); assert.equal(unread(overflow), 0);
cases++;
const interrupted = create('ucore');
start(interrupted, 'writer', 600); run(interrupted, 'writer');
assert.equal(interrupted.writer.done, 512);
start(interrupted, 'reader', 137); run(interrupted, 'reader');
close(interrupted, 'reader');
assert.equal(run(interrupted, 'writer').result, -1);
assert.equal(interrupted.writer.done, 512);
assert.equal(unread(interrupted), 375);
close(interrupted, 'writer');
assert.equal(interrupted.released, true); assert.equal(unread(interrupted), 0);
cases++;
for (const kernel of ['rcore', 'ucore']) {
  const eof = create(kernel);
  start(eof, 'writer', 5); run(eof, 'writer'); close(eof, 'writer');
  start(eof, 'reader', 12);
  assert.equal(run(eof, 'reader').result, 5);
  assert.equal(unread(eof), 0);
  cases++;
}
for (const length of [-1, 4097, .5, NaN]) assert.throws(() => start(create('rcore'), 'reader', length), RangeError);
assert.throws(() => create('unknown'), RangeError);
assert.throws(() => run(create('rcore'), 'reader'));
console.log(`${cases} pipe scenarios passed, including full 3000-byte FIFO checks for both kernels`);
