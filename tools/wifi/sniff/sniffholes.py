"""sniffholes.py <rec.bin> <run dir> <AP MAC> <headset MAC>: where do late frames come from? Needs a frameprobe run with FP_CHIRP=1.
1. Finds the chirps (UDP packets of 1111/1222/1333 bytes sent on a quiet link at the start and the end) among the AP's
   data frames and fits MAC time (TSFT) to the PC's perf counter, so every frame's send time is known in sniffer time.
2. From the headset's BlockAcks: every MPDU that the headset reported missing while later ones had arrived (a hole)
   and when it was finally acknowledged. A hole holds back everything after it in the headset's reorder buffer.
3. For each late frame: the longest hole open during it, and when it closed relative to the frame's completion."""
import bisect
import collections
import csv
import os
import statistics
import struct
import sys

REC = struct.Struct('<qqHHHHBBHBbIBHHQ')
src, run = sys.argv[1], sys.argv[2]
AP, HS = sys.argv[3].lower(), sys.argv[4].lower()  # the AP's BSSID and the headset's Wi-Fi MAC
macs = open(src + '.macs').read().split()
ap, hs = macs.index(AP), macs.index(HS)
raw = open(src, 'rb').read()
recs = [REC.unpack_from(raw, i * REC.size) for i in range(len(raw) // REC.size)]
recs = [r for r in recs if not r[12]]
typ = lambda r: (r[2] >> 2) & 3
sub = lambda r: (r[2] >> 4) & 15

# 1. chirps: IPv4 + UDP adds 28 bytes; QoS header + CCMP + LLC + MIC add 50, A-MSDU framing 14 more (+ padding)
ch = [l.split() for l in open(os.path.join(run, 'chirp.txt'))]
sent0 = int(ch[0][2])
chirps = [(tag, int(n), int(ns)) for tag, n, ns in ch[1:]]
dl = [r for r in recs if typ(r) == 2 and r[4] == ap and r[3] == hs]
ul = [r for r in recs if typ(r) == 2 and r[4] == hs and r[3] == ap]
# the sniffer may miss a chirp itself but catch the headset's echo of it (tsecho adds 24 bytes; ~0.2 ms later)
sizes = [n for tag, n, ns in chirps[:3]]
ways = [('down', dl, [{n + 78, n + 92, n + 94} for n in sizes], 0), ('echo', ul, [{n + 102} for n in sizes], 200)]
pts = []
for name, frames, want, lag in ways:
    hits = [[r[1] for r in frames if r[5] in w and not r[2] & 0x0800] for w in want]
    # triples whose spacing matches the PC's sends within 3 ms; the earliest is the start chirp, the latest the end one
    sent = {tag: [ns for t, n, ns in chirps if t == tag] for tag in ('start', 'end')}
    sp = sent['start']
    triples = sorted((a, b, c) for a in hits[0] for b in hits[1] for c in hits[2]
                     if abs((b - a) - (sp[1] - sp[0]) / 1000) + abs((c - b) - (sp[2] - sp[1]) / 1000) < 3000)
    if not triples:
        continue
    picks = {'start': triples[0]}
    if triples[-1][0] - triples[0][0] > 60e6:
        picks['end'] = triples[-1]
    for tag, tr in picks.items():
        for ns, t in zip(sent[tag], tr):
            pts.append((ns / 1000, t - lag))
# keep one point per send: the earliest MAC time (the chirp itself beats its echo)
uniq = {}
for x, y in pts:
    uniq[x] = min(uniq.get(x, y), y)
pts = sorted(uniq.items())
print('chirps found %d of %d' % (len(pts), len(chirps)))
if len(pts) < 2:
    sys.exit('not enough chirps to line up the capture')
xs, ys = zip(*pts)
mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
k = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs)
res = [y - (my + k * (x - mx)) for x, y in pts]
print('MAC/PC clock rate %.6f, chirp residuals µs: %s' % (k, ' '.join('%.0f' % v for v in res)))
pc2mac = lambda us: my + k * (us - mx)  # PC perf µs -> MAC µs (air arrival; includes the wired + AP delay)

# 2. holes from the headset's BlockAcks (TID 0 assumed: the stream and the plain probes)
bas = sorted((r[1], r[14], r[15]) for r in recs if typ(r) == 1 and sub(r) == 9 and r[4] == hs)
last = None
unwrap = {}


def absseq(s):
    global last
    if last is None:
        last = s
        return s
    d = (s - last) % 4096
    if d >= 2048:
        d -= 4096
    last += d
    return last


acked, missing = {}, {}
for t, ssn, bmp in bas:
    base = absseq(ssn)
    top = bmp.bit_length()
    for b in range(top):
        s = base + b
        if bmp >> b & 1:
            acked.setdefault(s, t)
        elif s not in acked:
            missing.setdefault(s, t)
holes = sorted((missing[s], acked.get(s), s) for s in missing)
closed = [(a, b, s) for a, b, s in holes if b is not None]
never = [s for a, b, s in holes if b is None]
dur = sorted((b - a) / 1000 for a, b, s in closed)
print('BlockAcks %d; holes %d, closed %d, never closed %d; hole length ms median %.2f, p90 %.2f, p99 %.2f, max %.1f' % (
    len(bas), len(holes), len(closed), len(never), statistics.median(dur), dur[len(dur) * 9 // 10], dur[len(dur) * 99 // 100], dur[-1]))
# retransmissions seen (retry bit) per sequence number
retx = collections.defaultdict(list)
for r in dl:
    if r[2] & 0x0800:
        retx[r[13]].append(r[1])
bars = [r[1] for r in recs if typ(r) == 1 and sub(r) == 8 and r[4] == ap]
print('BlockAckReq from the AP: %d' % len(bars))

# 3. per frame
fr = [(int(r['seq']), float(r['t_s']), float(r['excess_ms']), float(r['recv_ms']))
      for r in csv.DictReader(open(os.path.join(run, 'frames.csv')))]
HO = [h[0] for h in closed]


def hole_during(t0, t1):
    i = bisect.bisect_left(HO, t0 - 30000)
    best = None
    for a, b, s in closed[i:]:
        if a > t1:
            break
        if b >= t0 and (best is None or b - a > best[1] - best[0]):
            best = (a, b, s)
    return best


def describe(f):
    t = pc2mac((sent0 + f[1] * 1e9) / 1000)
    end = t + (8.33 + max(f[2], 0)) * 1000 + 3000
    h = hole_during(t, end)
    return t, h


late = [f for f in fr if f[2] > 8 and f[1] >= 10]
norm = [f for f in fr if f[2] < 2 and f[1] >= 10][::100]
print('\nlate frames %d:' % len(late))
L = []
for f in late:
    t, h = describe(f)
    if h:
        a, b, s = h
        L.append((b - a) / 1000)
        print('  frame %d +%.1f ms (receive %.1f ms): hole of %.1f ms on MPDU %d, opened %+.1f ms and closed %+.1f ms from send; '
              'retransmissions seen %d, BlockAckReq in hole %d' % (
                  f[0], f[2], f[3], (b - a) / 1000, s, (a - t) / 1000, (b - t) / 1000,
                  len([x for x in retx.get(s % 4096, []) if a - 1000 <= x <= b + 1000]),
                  sum(1 for x in bars if a <= x <= b)))
    else:
        L.append(0)
        print('  frame %d +%.1f ms: no hole' % (f[0], f[2]))
N = [((describe(f)[1][1] - describe(f)[1][0]) / 1000 if describe(f)[1] else 0) for f in norm]
print('\nlongest hole during the frame, median: late %.1f ms, normal %.1f ms; with a hole > 5 ms: late %d of %d, normal %d of %d' % (
    statistics.median(L) if L else 0, statistics.median(N) if N else 0,
    sum(1 for x in L if x > 5), len(L), sum(1 for x in N if x > 5), len(N)))
