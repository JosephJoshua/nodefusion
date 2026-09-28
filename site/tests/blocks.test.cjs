const assert = require('node:assert/strict');
const {locate} = require('../src/diagrams/blocks.js');
for (const [kernel, offset, level, indices, within] of [
  ['rcore', 0, 0, [0], 0], ['rcore', 13823, 0, [26], 511],
  ['rcore', 13824, 1, [0], 0], ['rcore', 79359, 1, [127], 511],
  ['rcore', 79360, 2, [0, 0], 0], ['rcore', 144896, 2, [1, 0], 0],
  ['rcore', 8467967, 2, [127, 127], 511],
  ['ucore', 12287, 0, [11], 1023], ['ucore', 12288, 1, [0], 0],
  ['ucore', 274431, 1, [255], 1023]
]) {
  const actual = locate(kernel, offset);
  assert.equal(actual.level, level);
  assert.deepEqual(actual.indices, indices);
  assert.equal(actual.within, within);
  assert.equal(actual.logical * actual.blockSize + actual.within, offset);
}
for (const [kernel, offset] of [['rcore', -1], ['rcore', 8467968], ['ucore', 274432], ['ucore', NaN], ['rcore', .5], ['unknown', 0]]) assert.throws(() => locate(kernel, offset), RangeError);
console.log('10 index-boundary cases and 6 invalid inputs passed');
