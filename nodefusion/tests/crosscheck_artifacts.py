import sys,json,collections,zlib,base64,re
sys.path.insert(0,'.')
from pathlib import Path
from nodefusion.host import nftrace as nf
RD=Path('/tmp/nf_runs/rcore-ch4')
tr=nf.load(RD/'trace.nfb'); fails=[]
evs=[json.loads(l) for l in open(RD/'events.jsonl',encoding='utf-8')]
meta=[e for e in evs if e.get('type')=='meta'][0]
evs=[e for e in evs if e.get('type')!='meta']
b=re.search(r'type="application/nodefusion"[^>]*>\s*([A-Za-z0-9+/=]+)\s*<',
            (RD/'rcore-ch4.html').read_text(encoding='utf-8')).group(1)
run=json.loads(zlib.decompress(base64.b64decode(b)))
def ck(c,msg):
    print(f'  {"OK  " if c else "FAIL"} {msg}')
    if not c: fails.append(msg)
ck(meta['total_insns']==tr.total_insns, 'events.jsonl meta 指令数 == 轨迹')
ck(len(evs)==len(tr.discons),          f'事件数 {len(evs)} == 轨迹 discon 数')
ck(all(0<=e['insn']<=tr.total_insns for e in evs if e.get('insn') is not None),
                                        '事件指令号全部在 [0, total] 内')
ck(evs==sorted(evs,key=lambda e:e.get('insn') or 0), '事件按指令号单调不减')
ck(len(run['events']['insn'])==len(evs), 'HTML 事件数 == jsonl')
ck(len(run['states'])==len(tr.snapshots),'HTML 快照数 == 轨迹')
ck(run['meta']['total_insns']==tr.total_insns,'HTML 指令数 == 轨迹')
mt=run['metrics']
ck(all(mt[k] is None for k in ('kalloc','kfree','context_switches','disk_io',
                               'page_table_maps','log_commits','forks','execs')),
   '无观测点的指标一律 null（不是 0）')
ck(all(isinstance(mt[k],int) for k in ('syscalls','page_faults','timer_interrupts')),
   'CSR 可直接观测的指标是真整数')
ck(bool(mt.get('unobservable_reason')),  'null 指标附带了原因说明')
ck(all(s['used'] is None and s['free'] is None for s in run['states']),
   '无空闲链表时 used/free 为 null')
ck(all(s['total']==32768 for s in run['states']), '每个快照总页数 == 32,768')
kinds=run['dict']['kinds']
ck(collections.Counter(kinds[k] for k in run['events']['kind'])==
   collections.Counter(e['kind'] for e in evs), 'HTML 与 jsonl 事件分布一致')
ck({s['pt_root_src'] for s in run['states']}<={'observed-satp',''},
   '页表根来源只有 observed-satp 或空')
ck(all(not s['pt_errors'] for s in run['states']), '真实运行没有未走完的页表')

MAXS = 2**53 - 1
bad = []
def _scan(o):
    if isinstance(o, dict):
        for v in o.values(): _scan(v)
    elif isinstance(o, list):
        for v in o: _scan(v)
    elif isinstance(o, int) and not isinstance(o, bool) and abs(o) > MAXS:
        bad.append(o)
_scan(run)
ck(not bad, f'没有超出 double 精度的裸整数（发现 {len(bad)} 个：'
            f'{[hex(x) for x in bad[:3]]}）')

print()
if fails: print('!! 失败:');[print('   ',f) for f in fails];sys.exit(1)
print('产物对账全部通过')
