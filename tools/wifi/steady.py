"""steady.py <runs dir>: re-summarize every owprobe run without its first 10 s (TCP ramp-up of the load).
Per run: minutes measured, lost down/up %, down/up excess p99 / p99.9 / max, and stalls >= 30 ms per minute
(runs of probes that are lost or have RTT > 20 ms, spanning at least 10 ms of sends + 20 ms)."""
import csv
import glob
import os
import sys

WARM = 10.0
print('%-28s %5s %7s %7s | %5s %6s %5s | %5s %6s %5s | %6s' % (
    'run', 'min', 'lostDn%', 'lostUp%', 'dn99', 'dn99.9', 'dnMax', 'up99', 'up99.9', 'upMax', 'st/min'))
for d in sorted(glob.glob(os.path.join(sys.argv[1], '*'))):
    s, l = os.path.join(d, 'owseries.csv'), os.path.join(d, 'lost.csv')
    if not (os.path.exists(s) and os.path.exists(l)):
        continue
    rows = [r for r in csv.DictReader(open(s)) if float(r['t_s']) >= WARM]
    lost = [r for r in csv.DictReader(open(l)) if float(r['t_s']) >= WARM]
    if not rows:
        continue
    span = (max(float(r['t_s']) for r in rows) - WARM) / 60
    n = len(rows) + len(lost)
    dn = sorted(float(r['down_excess_ms']) for r in rows)
    up = sorted(float(r['up_excess_ms']) for r in rows)
    p = lambda v, q: v[min(len(v) - 1, int(q / 100 * len(v)))]
    # stalls over the probe timeline
    ev = sorted([(float(r['t_s']), float(r['rtt_ms']) > 20 + 0 * 1) for r in rows] + [(float(r['t_s']), True) for r in lost])
    stalls, start, last = 0, None, None
    for t, bad in ev:
        if bad:
            start = t if start is None else start
            last = t
        elif start is not None:
            if (last - start) * 1000 + 20 >= 30:
                stalls += 1
            start = None
    ld = sum(1 for r in lost if r['dir'] == 'down')
    lu = sum(1 for r in lost if r['dir'] == 'up')
    print('%-28s %5.1f %7.3f %7.3f | %5.1f %6.1f %5.0f | %5.1f %6.1f %5.0f | %6.1f' % (
        os.path.basename(d)[:28], span, 100 * ld / n, 100 * lu / n, p(dn, 99), p(dn, 99.9), dn[-1],
        p(up, 99), p(up, 99.9), up[-1], stalls / span if span else 0))
