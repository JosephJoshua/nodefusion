(function (root) {
  'use strict';
  const actors = ['A', 'B', 'C'];
  function create(mechanism, permits = 0) {
    if (!['mutex', 'condvar', 'semaphore'].includes(mechanism) || !Number.isInteger(permits) || permits < 0 || permits > 3) throw new RangeError('Invalid synchronization experiment');
    return {mechanism, owner: null, count: permits, lockQueue: [], conditionQueue: [], permitQueue: [],
      threads: Object.fromEntries(actors.map(actor => [actor, {blocked: null, reacquire: false}])),
      message: mechanism === 'semaphore' ? `初始许可数为 ${permits}。` : '锁空闲，选择线程发起操作。', event: null};
  }
  function allowed(state, actor, operation) {
    if (!actors.includes(actor)) return false;
    const thread = state.threads[actor];
    if (!thread || thread.blocked) return false;
    if (thread.reacquire) return operation === 'lock';
    if (state.mechanism === 'semaphore') return ['down', 'up'].includes(operation);
    if (operation === 'lock') return state.owner !== actor;
    if (operation === 'unlock') return state.owner === actor;
    if (operation === 'wait') return state.mechanism === 'condvar' && state.owner === actor;
    if (operation === 'signal') return state.mechanism === 'condvar';
    return false;
  }
  function release(state) {
    const next = state.lockQueue.shift();
    state.owner = next || null;
    if (next) { state.threads[next].blocked = null; state.threads[next].reacquire = false; }
    return next;
  }
  function apply(state, actor, operation) {
    if (!allowed(state, actor, operation)) throw new Error('Operation unavailable');
    const next = structuredClone(state), thread = next.threads[actor];
    let target = null;
    if (operation === 'lock') {
      if (!next.owner) {
        next.owner = actor; thread.reacquire = false;
        next.message = `${actor} 获得锁${state.threads[actor].reacquire ? '，cond_wait 返回' : ''}。`;
      } else {
        thread.blocked = 'lock'; next.lockQueue.push(actor);
        next.message = `${actor} 等待 ${next.owner} 释放锁，进入锁的等待队列。`;
      }
    } else if (operation === 'unlock') {
      target = release(next);
      next.message = target ? `${actor} 将锁交给 ${target}。${target} 已获锁并就绪，locked 保持为 1。` : `${actor} 解锁，locked 变为 0。`;
    } else if (operation === 'wait') {
      target = release(next); thread.blocked = 'condition'; thread.reacquire = true; next.conditionQueue.push(actor);
      next.message = `${actor} 释放锁并等待条件变量。${target ? `锁交给 ${target}。` : '锁变为空闲。'}`;
    } else if (operation === 'signal') {
      target = next.conditionQueue.shift() || null;
      if (target) next.threads[target].blocked = null;
      next.message = target ? `${actor} 唤醒 ${target}。${target} 就绪，恢复 cond_wait 后还需重新加锁。` : `${actor} 发出通知，条件变量没有等待线程；通知不保留。`;
    } else if (operation === 'down') {
      next.count--;
      if (next.count < 0) { thread.blocked = 'permit'; next.permitQueue.push(actor); }
      next.message = next.count < 0 ? `${actor} 的 down 阻塞，count = ${next.count}。` : `${actor} 获得许可，down 返回；count = ${next.count}。`;
    } else if (operation === 'up') {
      next.count++;
      if (next.count <= 0) {
        target = next.permitQueue.shift(); next.threads[target].blocked = null;
      }
      next.message = target ? `${actor} 将许可交给 ${target}。${target} 就绪，down 恢复后不再减数。` : `${actor} 增加一个许可，count = ${next.count}。`;
    }
    next.event = {actor, operation, target};
    return next;
  }
  const model = {actors, create, allowed, apply};
  if (typeof module !== 'undefined') module.exports = model;
  root.SyncModel = model;
})(typeof globalThis === 'undefined' ? this : globalThis);
