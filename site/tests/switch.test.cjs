const assert = require('node:assert/strict');
const {stepsFor} = require('../src/diagrams/switch.js');

for (const kernel of ['rcore', 'ucore']) {
  for (const scenario of ['yield', 'timer', 'exit', 'alone']) {
    const steps = stepsFor(kernel, scenario);
    assert.ok(steps.length >= 6);
    assert.equal(steps[0].count, 0);
    assert.equal(steps.at(-1).count, kernel === 'ucore' ? 2 : scenario === 'alone' ? 0 : 1);
    assert.equal(steps.at(-1).current, scenario === 'alone' ? 'A' : 'B');
    for (let i = 1; i < steps.length; i++) {
      assert.ok(steps[i].count >= steps[i - 1].count);
      assert.ok(steps[i].count - steps[i - 1].count <= 1);
    }
    if (scenario === 'exit') {
      assert.equal(steps.at(-1).aState, kernel === 'rcore' ? 'Exited' : 'UNUSED');
    }
    if (scenario === 'timer') assert.match(steps[1].title, /时钟中断/);
    if (kernel === 'ucore') {
      const scheduler = steps.find(s => s.execution === 'scheduler：内核态');
      assert.equal(scheduler.current, 'A（上一进程）');
      assert.equal(scheduler.count, 1);
    }
  }
}
assert.throws(() => stepsFor('unknown', 'yield'), RangeError);
assert.throws(() => stepsFor('rcore', 'unknown'), RangeError);
console.log('8 scheduling scenarios passed');
