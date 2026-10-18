"""pfwho.py <trace> <prefix> <t0 offset> <race s>...: per given second of the race (as slowlog.py prints them), the
processes and threads with the most CPU time from 100 ms before to 50 ms after it, against their race average; and when
kswapd0 / kcompactd0 / perf_service ran (seconds of the race with over 5 ms of CPU)."""
import sys
from collections import defaultdict
from perfetto.trace_processor import TraceProcessor
trace, prefix = sys.argv[1], sys.argv[2]
marks = [float(x) for x in sys.argv[3:]]
off = int(open(prefix + '_stale.csv').readline().split('=')[1])
rows = [r for r in (l.split(',') for l in open('ft_%s.csv' % prefix).read().splitlines()[1:]) if len(r) == 5 and r[4]]
A, B = float(rows[0][1]) + 3, float(rows[-1][1]) - 1
v = [[float(x) for x in l.split(',')] for l in open(prefix + '_video.csv').read().splitlines()[1:]]
v = [x for x in v if A <= x[0] / 1e6 <= B]
t0 = int(min(v[0][1], v[0][3]) * 1e6); t1 = int(max(v[-1][2], v[-1][4]) * 1e6)
tp = TraceProcessor(trace=trace)
tot = defaultdict(float)
for r in tp.query("select coalesce(p.name, t.name) || ' / ' || t.name k, sum(min(s.ts + s.dur, %d) - max(s.ts, %d)) d from sched s join thread t using(utid) "
                  "left join process p using(upid) where t.tid != 0 and s.ts < %d and s.ts + s.dur > %d group by 1" % (t1, t0, t1, t0)):
    tot[r.k] = r.d / (t1 - t0)
for m in marks:
    a, b = t0 + int((m - 0.1) * 1e9), t0 + int((m + 0.05) * 1e9)
    got = []
    for r in tp.query("select coalesce(p.name, t.name) || ' / ' || t.name k, sum(min(s.ts + s.dur, %d) - max(s.ts, %d)) d from sched s join thread t using(utid) "
                      "left join process p using(upid) where t.tid != 0 and s.ts < %d and s.ts + s.dur > %d group by 1" % (b, a, b, a)):
        got.append((r.d / (b - a), r.k))
    got.sort(key=lambda g: -(g[0] - tot.get(g[1], 0)))
    print('%.2f s:' % m, ';  '.join('%s %.2f (avg %.2f)' % (k[-48:], d, tot.get(k, 0)) for d, k in got[:6]))
for name in ('kswapd0', 'kcompactd0', '%perf_service%'):
    secs = []
    for r in tp.query("select (s.ts - %d) / 1000000000 sec, sum(s.dur) d from sched s join thread t using(utid) left join process p using(upid) "
                      "where (t.name like '%s' or p.name like '%s') and s.ts between %d and %d group by 1 having d > 5000000" % (t0, name, name, t0, t1)):
        secs.append('%d:%.0f' % (r.sec, r.d / 1e6))
    print(name, ' '.join(secs))
