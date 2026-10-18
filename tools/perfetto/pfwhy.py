"""pfwhy.py <label>...: for each repeated frame in the race of a traced replay: the video frame VD waited for (the one
decoded last before the late app frame's xrEndFrame ended): when its data reached VD and when both eyes were decoded,
against a steady grid (ms late), and each eye's decode time; and how late VD's app frame was."""
import bisect
import statistics
import sys
for label in sys.argv[1:]:
    p = label + '_1'
    rows = [r for r in (l.split(',') for l in open('ft_%s.csv' % p).read().splitlines()[1:]) if len(r) == 5 and r[4]]
    A, B = float(rows[0][1]) + 3, float(rows[-1][1]) - 1
    v = [[float(x) for x in l.split(',')] for l in open(p + '_video.csv').read().splitlines()[1:]]
    v = [x for x in v if A <= x[0] / 1e6 <= B]
    per = statistics.median([b[0] - a[0] for a, b in zip(v, v[1:])]) / 1e3

    def grid(t):
        out = []
        for i in range(len(t)):
            a, b = max(0, i - 30), min(len(t), i + 30)
            out.append(t[i] - min(t[j] - (j - i) * per for j in range(a, b)))
        return out
    arr = [min(x[1], x[3]) for x in v]; done = [max(x[2], x[4]) for x in v]
    ga, gd = grid(arr), grid(done)
    fr = {int(c[0]): c for c in (l.split(',') for l in open(p + '_frames.csv').read().splitlines()[1:])}
    st = [l.split(',') for l in open(p + '_stale.csv').read().splitlines()[2:] if l]
    print('%s: median arrival %.2f / decoded %.2f ms off the grid' % (label, statistics.median(ga), statistics.median(gd)))
    for s in st:
        if not done[0] <= float(s[1]) <= done[-1]:
            continue
        c = fr.get(int(s[2]))
        e = float(c[5]) if c and c[5] else float(s[1])
        i = bisect.bisect_right(done, e) - 1
        print('  %.1f s into the race: app frame late %s ms; video frame: arrival %.2f, decoded %.2f off the grid; '
              'decode %.2f / %.2f ms; decoded %.2f ms before xrEndFrame end; app work %s ms' % (
                  (float(s[1]) - done[0]) / 1e3, s[3], ga[i], gd[i], v[i][2] - v[i][1], v[i][4] - v[i][3], e - done[i],
                  '%.2f' % (float(c[5]) - float(c[2])) if c and c[2] and c[5] else '?'))
