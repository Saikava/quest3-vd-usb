"""pfdec.py <label>...: the headset's video decoding in the race of traced replays (pf/<label>_1_video.csv and
_stale.csv/_frames.csv from pfstale.py/pfvideo.py, ft_<label>_1.csv for the race's span: the video frames' T is the
PC's QPC clock in us). Per run: each eye's decode time (data handed to the decoder -> decoded), the frames with a
decode over 12 / 16 ms per minute, the moment both eyes are decoded against a steady grid, and the repeated frames."""
import statistics
import sys


def pct(x, p):
    x = sorted(x); return x[min(len(x) - 1, int(p * len(x)))]


print('%-12s %6s %21s %21s %10s %16s %8s' % ('run', 'min', 'eye 1 med/p99/p99.9', 'eye 2 med/p99/p99.9', '>12/>16 /min',
                                            'decoded late p99/p99.9', 'stale/min'))
for label in sys.argv[1:]:
    p = '%s_1' % label
    try:
        rows = [l.split(',') for l in open('ft_%s.csv' % p).read().splitlines()[1:]]
    except OSError:
        print('%-12s no frame times' % label); continue
    rows = [r for r in rows if len(r) == 5 and r[4]]
    A, B = float(rows[0][1]) + 3, float(rows[-1][1]) - 1
    v = [[float(x) for x in l.split(',')] for l in open(p + '_video.csv').read().splitlines()[1:]]
    v = [x for x in v if A <= x[0] / 1e6 <= B]
    if len(v) < 1000:
        print('%-12s too few frames (%d)' % (label, len(v))); continue
    e1 = [x[2] - x[1] for x in v]; e2 = [x[4] - x[3] for x in v]
    worst = [max(a, b) for a, b in zip(e1, e2)]
    mins = (v[-1][0] - v[0][0]) / 6e7
    per = statistics.median([b[0] - a[0] for a, b in zip(v, v[1:])]) / 1e3
    done = [max(x[2], x[4]) for x in v]
    late = []
    for i in range(len(done)):
        a, b = max(0, i - 30), min(len(done), i + 30)
        late.append(done[i] - min(done[j] - (j - i) * per for j in range(a, b)))
    # repeated frames in the race window (boot clock: the decoded times' span)
    st = [l.split(',') for l in open(p + '_stale.csv').read().splitlines()[2:] if l]
    lo, hi = min(done), max(done)
    ns = sum(1 for s in st if lo <= float(s[1]) <= hi)
    print('%-12s %6.2f %6.2f %6.2f %7.2f %6.2f %6.2f %7.2f %5.1f %4.1f %7.2f %7.2f %8.2f' % (
        label, mins, pct(e1, .5), pct(e1, .99), pct(e1, .999), pct(e2, .5), pct(e2, .99), pct(e2, .999),
        sum(1 for w in worst if w > 12) / mins, sum(1 for w in worst if w > 16) / mins, pct(late, .99), pct(late, .999),
        ns / mins))
