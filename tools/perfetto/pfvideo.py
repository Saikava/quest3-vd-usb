"""pfvideo.py <trace> <prefix>: VD's video frames in a Perfetto trace, one by one. VD decodes two streams (two
c2 decoders, #id); each video frame (its timestamp ts=T, the same in both) is handed to a decoder when its data has
arrived ("CCodecBufferChannel::queue(...#id@ts=T)") and comes out decoded ("CCodecBufferChannel::onWorkDone(...)").
Writes <prefix>_video.csv (T; per decoder the queue and done times in ms of the boot clock) and prints how regularly
the frames arrived (each arrival against a steady grid fitted to the arrivals around it), how long they took to
decode, and the same for the frames VD waited for at each repeated frame (<prefix>_stale.csv from pfstale.py)."""
import bisect
import re
import statistics
import sys
from collections import defaultdict

from perfetto.trace_processor import TraceProcessor

trace, out = sys.argv[1], sys.argv[2]
tp = TraceProcessor(trace=trace)
pat = re.compile(r'CCodecBufferChannel::(queue|onWorkDone)\(c2\.[\w.]+#(\d+)@ts=(\d+)\)')
v = defaultdict(dict)   # T -> {(kind, decoder): ts}
decs = set()
for r in tp.query("select ts, name from slice where name like 'CCodecBufferChannel::queue(%' or "
                  "name like 'CCodecBufferChannel::onWorkDone(%'"):
    m = pat.match(r.name)
    if m:
        k, d, t = m.group(1), int(m.group(2)), int(m.group(3))
        decs.add(d)
        v[t].setdefault((k, d), r.ts)
decs = sorted(decs)
# the race's decoders: the two with the most frames
cnt = {d: sum(1 for x in v.values() if ('onWorkDone', d) in x) for d in decs}
decs = sorted(sorted(decs, key=lambda d: -cnt[d])[:2])
T = sorted(t for t, x in v.items() if all(('queue', d) in x and ('onWorkDone', d) in x for d in decs))
with open(out + '_video.csv', 'w') as o:
    o.write('T,' + ','.join('queue_%d_ms,done_%d_ms' % (d, d) for d in decs) + '\n')
    for t in T:
        o.write('%d,%s\n' % (t, ','.join('%.3f,%.3f' % (v[t][('queue', d)] / 1e6, v[t][('onWorkDone', d)] / 1e6) for d in decs)))

arr = [min(v[t][('queue', d)] for d in decs) / 1e6 for t in T]          # the frame's data there (first decoder)
done = [max(v[t][('onWorkDone', d)] for d in decs) / 1e6 for t in T]    # both eyes decoded
dec = {d: [(v[t][('onWorkDone', d)] - v[t][('queue', d)]) / 1e6 for t in T] for d in decs}
per = statistics.median([b - a for a, b in zip(arr, arr[1:])])
# lateness of each arrival: against the grid k*per through the earliest arrivals of the 60 frames around it
late = []
for i in range(len(arr)):
    a, b = max(0, i - 30), min(len(arr), i + 30)
    base = min(arr[j] - (j - i) * per for j in range(a, b))
    late.append(arr[i] - base)


def pct(x, p):
    x = sorted(x); return x[min(len(x) - 1, int(p * len(x)))]


print('%d video frames (decoders %s), arrival period %.3f ms' % (len(T), decs, per))
print('arrival lateness against the steady grid: median %.2f, 99%% %.2f, 99.9%% %.2f, max %.2f ms' % (
    pct(late, .5), pct(late, .99), pct(late, .999), max(late)))
for d in decs:
    print('decoder #%d: decode time median %.2f, 99%% %.2f, 99.9%% %.2f, max %.2f ms' % (
        d, pct(dec[d], .5), pct(dec[d], .99), pct(dec[d], .999), max(dec[d])))
tot = [dn - a for a, dn in zip(arr, done)]
print('arrival to both decoded: median %.2f, 99%% %.2f, 99.9%% %.2f, max %.2f ms' % (
    pct(tot, .5), pct(tot, .99), pct(tot, .999), max(tot)))

# the repeated frames: the video frame decoded last before the late app frame's ingest
try:
    st = [l.split(',') for l in open(out + '_stale.csv').read().splitlines()[2:] if l]
except OSError:
    st = []
fr = {}
try:
    frames = open(out + '_frames.csv').read().splitlines()[1:]
except OSError:   # a light trace: no pfstale.py
    frames = []
for l in frames:
    c = l.split(',')
    fr[int(c[0])] = c
print('\nrepeated frames: the video frame the late app frame showed (decoded last before its xrEndFrame):')
for c in st:
    f = fr.get(int(c[2]))
    if not f or not f[5]:
        print('  display %s: frame %s not submitted' % (c[0], c[2])); continue
    e = float(f[5])
    i = bisect.bisect_right(done, e) - 1
    if i < 1:
        continue
    print('  display %s (late %s ms): video frame arrived %.2f ms off the grid (%.2f ms after the previous); decode %s; '
          'both decoded %.2f ms before xrEndFrame ended, %.2f ms after arrival' % (
              c[0], c[3], late[i], arr[i] - arr[i - 1], ' '.join('#%d %.2f' % (d, dec[d][i]) for d in decs),
              e - done[i], done[i] - arr[i]))
