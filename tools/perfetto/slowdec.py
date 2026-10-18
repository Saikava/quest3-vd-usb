"""slowdec.py <trace> <prefix> [min ms]: the slowest decodes of the race (from <prefix>_video.csv): what the decoder
HAL's threads (media.hwcodec: poll_*, EvtQ_*) did between the frame's queue and its done: running, runnable (and
on which CPU, who ran there), sleeping (waiting for the hardware)."""
import sys
from perfetto.trace_processor import TraceProcessor
trace, prefix = sys.argv[1], sys.argv[2]
thr = float(sys.argv[3]) if len(sys.argv) > 3 else 13
tp = TraceProcessor(trace=trace)
rows = [[float(x) for x in l.split(',')] for l in open(prefix + '_video.csv').read().splitlines()[1:]]
n = len(rows); rows = rows[n // 8:]
th = list(tp.query("select t.utid, t.tid, t.name from thread t join process p using(upid) where p.name like 'media.hwcodec%' "
                   "and (t.name like 'poll_%' or t.name like 'EvtQ_%') order by t.tid"))
# the race's decoders: the threads that ran most in the middle of the run
mid0, mid1 = int(rows[len(rows) // 2][1] * 1e6), int(rows[len(rows) // 2 + 100][1] * 1e6)
busy = {r.utid: r.d for r in tp.query("select utid, sum(dur) d from sched where ts between %d and %d group by 1" % (mid0, mid1))}
th = [t for t in th if busy.get(t.utid, 0) > 0]
print('decoder threads:', ', '.join('%s %d' % (t.name, t.tid) for t in th))
slow = [r for r in rows if max(r[2] - r[1], r[4] - r[3]) > thr]
print('%d frames with a decode over %.0f ms' % (len(slow), thr))
for r in slow[:12] + [rows[len(rows) // 2]]:
    q = int(min(r[1], r[3]) * 1e6); d = int(max(r[2], r[4]) * 1e6)
    print('\nT %d: queue %.3f / %.3f, done +%.2f / +%.2f ms' % (r[0], 0, r[3] - r[1], r[2] - r[1], r[4] - r[1]))
    for t in th:
        parts = []
        for s in tp.query("select ts, dur, state, cpu from thread_state where utid = %d and ts < %d and ts + dur > %d order by ts" % (t.utid, d, q)):
            a = max(s.ts, q); b = min(s.ts + s.dur, d)
            if b - a >= 200000:
                parts.append('%+.1f %s%s %.1f' % ((a - q) / 1e6, s.state, '@%s' % s.cpu if s.cpu is not None else '', (b - a) / 1e6))
        print('  %-16s %s' % (t.name + ' ' + str(t.tid), '; '.join(parts)))
    # CPU load on all cores in the window
    load = list(tp.query("select cpu, sum(min(ts + dur, %d) - max(ts, %d)) busy from sched where ts < %d and ts + dur > %d and utid != 0 group by cpu" % (d, q, d, q)))
    print('  cpu busy %%: %s' % ' '.join('%d:%.0f' % (x.cpu, 100 * x.busy / (d - q)) for x in load))
