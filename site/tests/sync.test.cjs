const assert = require('node:assert/strict');
const {scenarios} = require('../src/diagrams/sync.js');

for (const [name, steps] of Object.entries(scenarios)) {
  for (const step of steps) {
    const waiting = step.queue.match(/[ABC]/g) || [];
    const blocked = step.states.flatMap((state, index) => state === 'blocked' ? ['ABC'[index]] : []);
    assert.deepEqual(waiting, blocked, `${name}: waiting threads match blocked states`);
    for (const thread of waiting) assert.ok(!step.ready.includes(thread), `${name}: blocked thread is not runnable`);
    if (name === 'semaphore') {
      const count = Number(step.resource.split('=')[1].trim().replace('−', '-'));
      assert.equal(Math.max(0, -count), waiting.length);
    }
  }
}
assert.match(scenarios.mutex[2].resource, /B 持有 · locked = 1/);
assert.equal(scenarios.mutex[2].states[1], 'ready');
assert.equal(scenarios.condvar[2].states[0], 'ready');
assert.equal(scenarios.condvar[3].queue, '互斥锁：A');
console.log('15 synchronization states passed: wait queues, handoff and semaphore counts');

const model = require('../src/diagrams/sync-model.js');
let lock = model.create('mutex');
for (const [actor, operation] of [['A', 'lock'], ['C', 'lock'], ['B', 'lock'], ['A', 'unlock']]) lock = model.apply(lock, actor, operation);
assert.equal(lock.owner, 'C');
assert.deepEqual(lock.lockQueue, ['B']);
assert.equal(lock.threads.C.blocked, null);
assert.ok(!model.allowed(lock, 'B', 'unlock'));

let condition = model.create('condvar');
for (const [actor, operation] of [['A', 'lock'], ['A', 'wait'], ['B', 'lock'], ['B', 'signal']]) condition = model.apply(condition, actor, operation);
assert.equal(condition.owner, 'B');
assert.equal(condition.threads.A.reacquire, true);
assert.equal(condition.threads.A.blocked, null);
assert.ok(!model.allowed(condition, 'A', 'signal'), 'cond_wait must reacquire before returning');
condition = model.apply(condition, 'A', 'lock');
assert.deepEqual(condition.lockQueue, ['A']);
condition = model.apply(condition, 'B', 'unlock');
assert.equal(condition.owner, 'A');
assert.equal(condition.threads.A.reacquire, false);
let lost = model.apply(model.create('condvar'), 'B', 'signal');
lost = model.apply(lost, 'A', 'lock'); lost = model.apply(lost, 'A', 'wait');
assert.equal(lost.threads.A.blocked, 'condition', 'Notifications are not stored');

function invariant(state) {
  const waiting = [...state.lockQueue, ...state.conditionQueue, ...state.permitQueue];
  assert.equal(new Set(waiting).size, waiting.length, 'A thread waits in one queue at most');
  for (const actor of model.actors) assert.equal(waiting.includes(actor), Boolean(state.threads[actor].blocked));
  if (state.owner) assert.ok(!waiting.includes(state.owner));
  if (state.mechanism === 'semaphore') assert.equal(Math.max(0, -state.count), state.permitQueue.length);
}
let transitions = 0;
for (const mechanism of ['mutex', 'condvar', 'semaphore']) {
  for (const permits of mechanism === 'semaphore' ? [0, 1, 2, 3] : [0]) {
    let frontier = [model.create(mechanism, permits)];
    const seen = new Set();
    for (let depth = 0; depth < 7; depth++) {
      const next = [];
      for (const state of frontier) {
        invariant(state);
        for (const actor of model.actors) for (const operation of ['lock', 'unlock', 'wait', 'signal', 'down', 'up']) {
          if (!model.allowed(state, actor, operation)) continue;
          const after = model.apply(state, actor, operation); invariant(after); transitions++;
          const key = JSON.stringify({...after, message: '', event: null});
          if (!seen.has(key)) { seen.add(key); next.push(after); }
        }
      }
      frontier = next;
    }
  }
}
console.log(`${transitions} free-operation transitions passed: FIFO, ownership, notification and permit invariants`);
