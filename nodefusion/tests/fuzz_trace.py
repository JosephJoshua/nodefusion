import random, sys, traceback
from pathlib import Path
sys.path.insert(0, '.')
from nodefusion.host import nftrace as nf

SRC = Path('/tmp/nf_runs/rcore-ch4/trace.nfb')
data = SRC.read_bytes()
base = nf.load(SRC)
print(f'基准：{base.total_insns:,} 指令，{len(base.snapshots)} 快照，{len(data):,} 字节')

rnd = random.Random(20260829)
tmp = Path('/tmp/nf_verify/fz.nfb')
tally = {'ok': 0, 'flagged': 0, 'raised': 0, 'BAD': 0}
bad = []

def classify(path, tag):
    try:
        t = nf.load(path)
    except Exception as e:
        return 'raised', f'{type(e).__name__}: {e}'[:110]
    if t.total_insns < 0 or len(t.snapshots) < 0:
        return 'BAD', '负数计数'
    if len(t.snapshots) > 10_000:
        return 'BAD', f'快照数暴涨 {len(t.snapshots)}'
    if t.total_insns > 10**15:
        return 'BAD', f'指令数暴涨 {t.total_insns}'
    for s in t.snapshots:
        if len(s.pages) > 200_000:
            return 'BAD', f'页数暴涨 {len(s.pages)}'
    return ('flagged' if getattr(t, 'truncated_at_eof', False) else 'ok'), ''

for i in range(160):
    n = rnd.randrange(0, len(data))
    tmp.write_bytes(data[:n])
    k, msg = classify(tmp, f'trunc@{n}')
    tally[k] += 1
    if k == 'BAD': bad.append(f'截断 {n}: {msg}')

for i in range(200):
    b = bytearray(data)
    pos = rnd.randrange(0, 4096) if i % 2 == 0 else rnd.randrange(0, len(b))
    b[pos] ^= 1 << rnd.randrange(8)
    tmp.write_bytes(bytes(b))
    k, msg = classify(tmp, f'flip@{pos}')
    tally[k] += 1
    if k == 'BAD': bad.append(f'翻转 {pos}: {msg}')

for i in range(120):
    b = bytearray(data)
    pos = rnd.randrange(0, max(1, len(b) - 8))
    b[pos:pos+8] = b'\xff' * 8
    tmp.write_bytes(bytes(b))
    k, msg = classify(tmp, f'max@{pos}')
    tally[k] += 1
    if k == 'BAD': bad.append(f'爆值 {pos}: {msg}')

for name, blob in (('空', b''), ('垃圾', bytes(rnd.randrange(256) for _ in range(5000))),
                   ('仅头部', data[:16]), ('头部+乱码', data[:64] + b'\x00' * 4096)):
    tmp.write_bytes(blob)
    k, msg = classify(tmp, name)
    tally[k] += 1
    if k == 'BAD': bad.append(f'{name}: {msg}')

print('结果:', tally)
if bad:
    print('!! 失败样例:')
    for b in bad[:15]: print('   ', b)
    sys.exit(1)
print('通过：没有一个变异体被读成"看起来正常"的伪造数据')
