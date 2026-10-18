"""vrapi90.py <logcatE> <frametimes.csv> <headset offset s>: VrApi per-second lines in the race window."""
import re, sys, time
from collections import Counter
log, ft, off = sys.argv[1], sys.argv[2], float(sys.argv[3])
QPC_TO_WALL = 3108.81
rows = [r for r in (l.split(',') for l in open(ft).read().splitlines()[1:]) if len(r) == 5 and r[4]]
A, B = (float(rows[0][1]) + QPC_TO_WALL) % 86400, (float(rows[-1][1]) + QPC_TO_WALL) % 86400   # a time of day
def tod(e):
    lt = time.localtime(e); return lt.tm_hour * 3600 + lt.tm_min * 60 + lt.tm_sec + e % 1
secs = []; nolatch = Counter(); other = Counter()
for l in open(log, encoding='utf-8', errors='replace'):
    m = re.match(r'\s*(\d+\.\d+)\s+\d+\s+\d+\s+\w\s+(\S+)\s*:\s?(.*)', l)
    if not m: continue
    t = tod(float(m.group(1)) - off)
    if not A <= t <= B: continue
    tag, msg = m.group(2), m.group(3)
    if tag == 'VrApi' and msg.startswith('FPS='):
        kv = dict(x.split('=', 1) for x in msg.split(',') if '=' in x)
        secs.append((t - A, kv))
    elif 'no latch time' in msg:
        nolatch[int(t - A)] += 1
print('race %.0f s, %d VrApi lines' % (B - A, len(secs)))
st = [(t, int(kv['Stale'])) for t, kv in secs]
tot = sum(s for _, s in st)
print('Stale total %d = %.2f/min (over the %d s with VrApi lines); seconds with stale: %s' % (tot, tot / max(len(st), 1) * 60, len(st), ' '.join('%.0f:%d' % (t, s) for t, s in st if s)))
print('FPS values:', Counter(kv['FPS'] for _, kv in secs).most_common(5))
print('Stale2/5/10/max nonzero:', [(round(t), kv['Stale2/5/10/max']) for t, kv in secs if kv['Stale2/5/10/max'] != '0/0/0/0'])
print('no latch time: total %d, seconds: %s' % (sum(nolatch.values()), ' '.join('%d:%d' % kv for kv in sorted(nolatch.items()))))
for k in ('Prd', 'GPU%', 'CPU4/GPU', 'App', 'TW'):
    print(k, Counter(kv.get(k) for _, kv in secs).most_common(4))
