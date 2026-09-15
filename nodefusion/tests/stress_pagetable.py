import sys, time, resource
sys.path.insert(0, '.')
from nodefusion.host.guest import (walk_pagetable, EM_RISCV,
                                   PGSIZE, PGSHIFT)
from nodefusion.host import guest as G

BASE = 0x8000_0000
NPG  = 4096

class FakeRam:
    def __init__(self, npg=NPG):
        self.base = BASE
        self.size = npg * PGSIZE
        self.buf = bytearray(self.size)
        self.seen = set(range(npg))
    def _off(self, pa):
        o = pa - self.base
        return o if 0 <= o < self.size else None
    def blob(self, pa, n):
        o = self._off(pa)
        if o is None or o + n > self.size: return None
        return bytes(self.buf[o:o+n])
    def page_seen(self, idx): return idx in self.seen
    def u64(self, pa):
        o = self._off(pa)
        if o is None or o + 8 > self.size: return None
        return int.from_bytes(self.buf[o:o+8], 'little')
    def put_pte(self, pa, idx, child_pa, flags):
        o = self._off(pa) + idx * 8
        pte = ((child_pa >> PGSHIFT) << 10) | flags
        self.buf[o:o+8] = pte.to_bytes(8, 'little')

V, R, W, X, U = G.PTE_V, G.PTE_R, G.PTE_W, G.PTE_X, G.PTE_U
fails = []

def check(name, fn, budget=20.0):
    t0 = time.time()
    try:
        maps, pts, err = fn()
    except RecursionError:
        fails.append(f'{name}: RecursionError（爆栈）'); return
    except Exception as e:
        print(f'  {name:28} 抛出 {type(e).__name__}: {e}'); return
    dt = time.time() - t0
    if dt > budget:
        fails.append(f'{name}: 耗时 {dt:.1f}s 超过预算 {budget}s')
    dup = len(pts) - len(set(pts))
    print(f'  {name:28} 叶子={len(maps):<8} pt页={len(pts):<6} 重复={dup:<6} '
          f'err={(err or "-")[:34]:36} {dt:.2f}s')
    return maps, pts, err, dup

r = FakeRam(); root = BASE
r.put_pte(root, 0, root, V)
check('自指 PTE', lambda: walk_pagetable(r, root, machine=EM_RISCV))

r2 = FakeRam(); a, b = BASE, BASE + PGSIZE
r2.put_pte(a, 0, b, V); r2.put_pte(b, 0, a, V)
check('两页互指', lambda: walk_pagetable(r2, a, machine=EM_RISCV))

r3 = FakeRam(); root3 = BASE
for i in range(512): r3.put_pte(root3, i, root3, V)
res = check('512 项全自指', lambda: walk_pagetable(r3, root3, machine=EM_RISCV))

r4 = FakeRam(); L2, L1, L0 = BASE, BASE+PGSIZE, BASE+2*PGSIZE
for i in range(512): r4.put_pte(L2, i, L1, V)
for i in range(512): r4.put_pte(L1, i, L0, V)
for i in range(512): r4.put_pte(L0, i, BASE+3*PGSIZE, V|R|W|U)
res4 = check('满扇出 512^3 叶子', lambda: walk_pagetable(r4, L0 and L2, machine=EM_RISCV))
if res4:
    maps, pts, err, dup = res4
    if err is None:
        fails.append('满扇出：叶子被截断却没有报错')
    lim = max(20000, (r4.size // PGSIZE) * 4)
    if len(maps) > lim + 512:
        fails.append(f'满扇出：超出上限太多 {len(maps)} > {lim}+512')

r5 = FakeRam()
res5 = check('根越界', lambda: walk_pagetable(r5, 0xDEAD_0000, machine=EM_RISCV))
if res5 and res5[2] is None: fails.append('根越界：没有报错')

res6 = check('根为 0', lambda: walk_pagetable(r5, 0, machine=EM_RISCV))
if res6 and res6[2] is None: fails.append('根为 0：没有报错')

r7 = FakeRam(); r7.seen.discard(1)
r7.put_pte(BASE, 0, BASE+PGSIZE, V)
res7 = check('页表页未被快照覆盖', lambda: walk_pagetable(r7, BASE, machine=EM_RISCV))
if res7 and res7[2] is None: fails.append('未覆盖页：没有报错')

print()
if fails:
    print('!! 失败:')
    for f in fails: print('   ', f)
    sys.exit(1)
print('通过')
