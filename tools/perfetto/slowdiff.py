"""slowdiff.py <trace> <prefix> [slow ms]: what differs on the headset while a video frame decodes slowly. Per video
frame (pfvideo.py's <prefix>_video.csv; the race only, from ft_<prefix>.csv): the span from its first eye's data
handed to the decoder to both eyes decoded; slow (over the threshold) against normal (within 1 ms of the median, every
5th such frame: spans not overlapping). For each class: CPU time per process (ms per ms of the spans, all CPUs), the
CPUs' frequencies, and the decoder HAL's threads' states."""
import statistics
import sys
from collections import defaultdict

from perfetto.trace_processor import TraceProcessor

trace, prefix = sys.argv[1], sys.argv[2]
slow_ms = float(sys.argv[3]) if len(sys.argv) > 3 else 13.0
rows = [r for r in (l.split(',') for l in open('ft_%s.csv' % prefix).read().splitlines()[1:]) if len(r) == 5 and r[4]]
A, B = float(rows[0][1]) + 3, float(rows[-1][1]) - 1
v = [[float(x) for x in l.split(',')] for l in open(prefix + '_video.csv').read().splitlines()[1:]]
v = [x for x in v if A <= x[0] / 1e6 <= B]
span = [(min(x[1], x[3]), max(x[2], x[4])) for x in v]
med = statistics.median(e - s for s, e in span)
slow = [(s, e) for s, e in span if e - s > slow_ms]
normal = [(s, e) for s, e in span if abs(e - s - med) < 1][::5]
print('%d frames, span median %.2f ms; %d slow (> %.0f ms), %d normal' % (len(span), med, len(slow), slow_ms, len(normal)))
tp = TraceProcessor(trace=trace)


def merged(win):
    out = []
    for s, e in sorted(win):
        if out and s <= out[-1][1]:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return out


tp.query("create table freq as select t.cpu, c.ts, lead(c.ts) over (partition by c.track_id order by c.ts) - c.ts dur, cast(c.value as int) value "
         "from counter c join cpu_counter_track t on c.track_id = t.id where t.name = 'cpufreq'")
tp.query("delete from freq where dur is null")
tp.query("create table hal as select s.ts, s.dur, s.utid, s.state from thread_state s join thread t using(utid) "
         "join process p using(upid) where p.name like '%media.hwcodec%' or p.name like '%codec2%'")


def per_class(win):
    win = merged(win)
    total = sum(e - s for s, e in win)
    for t in ('j', 'jf', 'jh'):
        tp.query('drop table if exists ' + t)
    tp.query('drop table if exists win')
    tp.query('create table win (ts int, dur int)')
    tp.query('insert into win values ' + ','.join('(%d,%d)' % (int(s * 1e6), int((e - s) * 1e6)) for s, e in win))
    tp.query("create virtual table j using span_join(win, sched partitioned cpu)")
    tp.query("create virtual table jf using span_join(win, freq partitioned cpu)")
    tp.query("create virtual table jh using span_join(win, hal partitioned utid)")
    cpu = defaultdict(float)
    for r in tp.query("select coalesce(p.name, t.name) pname, sum(j.dur) d from j join thread t using(utid) left join process p using(upid) "
                      "where t.tid != 0 group by 1"):
        cpu[r.pname] += r.d / 1e6 / total
    cpu['_freq'] = {r.cpu: r.mhz for r in tp.query("select cpu, sum(value * dur) / sum(dur) / 1e3 mhz from jf group by 1")}
    st = defaultdict(float)
    for r in tp.query("select t.name tname, jh.state, sum(jh.dur) d from jh join thread t using(utid) group by 1, 2"):
        st[(r.tname, r.state)] += r.d / 1e6 / total
    return cpu, st


cs, ss = per_class(slow)
cn, sn = per_class(normal)
fs, fn = cs.pop('_freq'), cn.pop('_freq')
print('CPU MHz in the spans, slow / normal: ' + '  '.join('%d: %.0f/%.0f' % (c, fs[c], fn[c]) for c in sorted(fs)))
print('\nCPU time per ms of the span (all CPUs): slow / normal / ratio')
keys = sorted(set(cs) | set(cn), key=lambda k: -(cs.get(k, 0) - cn.get(k, 0)))
for k in keys[:25]:
    print('  %-50s %6.3f %6.3f %6.2f' % (k[:50], cs.get(k, 0), cn.get(k, 0), cs.get(k, 0) / max(cn.get(k, 0), 1e-4)))
print('  ...')
for k in keys[-8:]:
    print('  %-50s %6.3f %6.3f %6.2f' % (k[:50], cs.get(k, 0), cn.get(k, 0), cs.get(k, 0) / max(cn.get(k, 0), 1e-4)))
print('\ndecoder HAL threads (share of the span): slow / normal')
for k in sorted(set(ss) | set(sn), key=lambda k: -max(ss.get(k, 0), sn.get(k, 0)))[:20]:
    print('  %-28s %-4s %6.3f %6.3f' % (k[0], k[1], ss.get(k, 0), sn.get(k, 0)))
