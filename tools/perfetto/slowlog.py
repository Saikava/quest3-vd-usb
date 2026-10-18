"""slowlog.py <prefix> [slow ms] [window ms]: the slow decodes of a traced run (pfvideo.py's <prefix>_video.csv, the race
from ft_<prefix>.csv) on the headset's wall clock (realtime - boottime from <prefix>_stale.csv's first line), and the
logcat lines (logcatE_<prefix>.txt, -v epoch) from the window before each one's start to its end, by tag: what the
headset logs around slow decodes, against its whole-race rate."""
import re
import statistics
import sys
from collections import Counter

prefix = sys.argv[1]
slow_ms = float(sys.argv[2]) if len(sys.argv) > 2 else 13.0
pre = float(sys.argv[3]) if len(sys.argv) > 3 else 200.0
off = int(open(prefix + '_stale.csv').readline().split('=')[1]) / 1e9
rows = [r for r in (l.split(',') for l in open('ft_%s.csv' % prefix).read().splitlines()[1:]) if len(r) == 5 and r[4]]
A, B = float(rows[0][1]) + 3, float(rows[-1][1]) - 1
v = [[float(x) for x in l.split(',')] for l in open(prefix + '_video.csv').read().splitlines()[1:]]
v = [x for x in v if A <= x[0] / 1e6 <= B]
span = [(min(x[1], x[3]) / 1e3 + off, max(x[2], x[4]) / 1e3 + off) for x in v]
t0, t1 = span[0][0], span[-1][1]
slow = [(s, e) for s, e in span if (e - s) * 1e3 > slow_ms]
print('%d slow decodes (> %.0f ms) in %.0f s; seconds into the race:' % (len(slow), slow_ms, t1 - t0))
print(' '.join('%.2f' % (s - t0) for s, e in slow))
near, allc, sample = Counter(), Counter(), {}
wins = [(s - pre / 1e3, e) for s, e in slow]
cover = sum(e - s for s, e in wins)
for l in open('logcatE_%s.txt' % prefix, encoding='utf-8', errors='replace'):
    m = re.match(r'\s*(\d+\.\d+)\s+\d+\s+\d+\s+(\w)\s+(.+?)\s*:\s?(.*)', l)
    if not m:
        continue
    t = float(m.group(1))
    if not t0 <= t <= t1:
        continue
    tag = m.group(3)
    allc[tag] += 1
    for s, e in wins:
        if s <= t <= e:
            near[tag] += 1
            sample.setdefault(tag, []).append('%8.3f %s' % (t - t0, m.group(4)[:160]))
            break
print('\ntag: lines per s near the slow decodes / in the whole race')
for tag, n in sorted(near.items(), key=lambda kv: -kv[1] / cover / max(allc[kv[0]] / (t1 - t0), 1e-9))[:25]:
    print('  %-34s %7.2f %7.2f' % (tag[:34], n / cover, allc[tag] / (t1 - t0)))
for tag, s in sorted(sample.items(), key=lambda kv: -near[kv[0]] / cover / max(allc[kv[0]] / (t1 - t0), 1e-9))[:8]:
    print('== %s' % tag)
    print('\n'.join(s[:8]))
