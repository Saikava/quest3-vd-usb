"""pfnet.py <prefix> <vd.pcapng> <frametimes.csv>: each video frame's way from the PC to the display, from the PC's
packet capture and the headset's Perfetto trace (pfstale.py and pfvideo.py outputs <prefix>_*.csv).

A video frame's codec timestamp T is the PC's QPC clock in microseconds (VD's capture of the game's frame); VD starts
sending it some 3 ms later. PC (capture; wall clock - QPC_TO_WALL = QPC): VD's burst of the frame (the first burst
starting after T: its first and last segment) and the headset's ACK of its last byte. Headset (trace, boot clock): the
frame handed to the decoders (its data read by VD) and both decoded; the boot clock is fitted to the QPC clock by the
ACKs (a line under all the frames' ACK-to-decoder times: so those are relative to the quickest). Race only (the frame
times' span). Prints how each stage varies, and for each repeated frame the chain of the video frame VD waited for."""
import bisect
import statistics
import struct
import sys
import time
from collections import Counter, defaultdict

QPC_TO_WALL = 3108.81
prefix, pcap, ft = sys.argv[1], sys.argv[2], sys.argv[3]


def tod(e):
    lt = time.localtime(e)
    return lt.tm_hour * 3600 + lt.tm_min * 60 + lt.tm_sec + e % 1


# --- PC: bursts
data = open(pcap, 'rb').read()
pos = 0; tsres = {}; nif = 0
out = defaultdict(list); acks = defaultdict(list); nb = Counter(); last = {}
while pos + 8 <= len(data):
    btype, blen = struct.unpack_from('<II', data, pos)
    if blen < 12:
        break
    if btype == 1:
        body = data[pos + 8:pos + blen - 4]; tsres[nif] = 1e-6; o = 8
        while o + 4 <= len(body):
            code, ln = struct.unpack_from('<HH', body, o)
            if code == 0:
                break
            if code == 9:
                v = body[o + 4]; tsres[nif] = 2.0 ** -(v & 0x7f) if v & 0x80 else 10.0 ** -v
            o += 4 + ((ln + 3) & ~3)
        nif += 1
    elif btype == 6:
        ifid, th, tl, cap, orig = struct.unpack_from('<IIIII', data, pos + 8)
        t = ((th << 32) | tl) * tsres.get(ifid, 1e-6); p0 = pos + 28
        if cap >= 74 and data[p0 + 12:p0 + 14] == b'\x86\xdd' and data[p0 + 20] == 6:
            ip = p0 + 14; plen = struct.unpack_from('>H', data, ip + 4)[0]; tcp = ip + 40
            sp, dp, seq, ack, offb, flags = struct.unpack_from('>HHIIBB', data, tcp); ln = plen - (offb >> 4) * 4
            if 38800 <= sp < 38900 and ln > 0:
                sig = (sp, dp, seq, ln)
                if t - last.get(sig, -1) >= 0.0002:
                    out[(sp, dp)].append((t, (seq + ln) & 0xffffffff, ln)); nb[(sp, dp)] += ln
                last[sig] = t
            elif 38800 <= dp < 38900 and flags & 0x10:
                acks[(dp, sp)].append((t, ack))
    pos += blen
del data
key = max(nb, key=nb.get)
AK = sorted(acks[key]); at = [a[0] for a in AK]
bursts = []   # [first send, last send, end seq, bytes, ack]
prev = None
for t, e, ln in out[key]:
    if prev is None or t - prev > 0.002:
        bursts.append([t, t, e, ln])
    else:
        bursts[-1][1] = t; bursts[-1][2] = e; bursts[-1][3] += ln
    prev = t
for b in bursts:
    i = bisect.bisect_left(at, b[1])
    while i < len(AK) and ((AK[i][1] - b[2]) & 0xffffffff) >= 1 << 31 and AK[i][0] - b[1] < 0.5:
        i += 1
    b.append(AK[i][0] if i < len(AK) and AK[i][0] - b[1] < 0.5 else None)
bursts = [b for b in bursts if b[4]]
back = [b[4] for b in bursts]

# --- headset: video frames (T: QPC us; boot clock ms)
vid = []
for l in open(prefix + '_video.csv').read().splitlines()[1:]:
    c = [float(x) for x in l.split(',')]
    vid.append((int(c[0]) / 1e6, min(c[1], c[3]) / 1e3, max(c[2], c[4]) / 1e3, (c[2] - c[1]) / 1e3, (c[4] - c[3]) / 1e3))
rows = [l.split(',') for l in open(ft).read().splitlines()[1:]]
rows = [r for r in rows if len(r) == 5 and r[4]]
A, B = float(rows[0][1]) + 3, float(rows[-1][1]) - 1     # QPC
bs = [tod(b[0]) - QPC_TO_WALL for b in bursts]
chain = []   # (T, send start, send end, ACK (QPC), arrival, done (boot), decode a, decode b, bytes)
for v in vid:
    if not A <= v[0] <= B:
        continue
    i = bisect.bisect_left(bs, v[0])
    if i >= len(bs) or bs[i] - v[0] > 0.015:
        continue
    b = bursts[i]
    chain.append((v[0], bs[i], tod(b[1]) - QPC_TO_WALL, tod(b[4]) - QPC_TO_WALL, v[1], v[2], v[3], v[4], b[3]))
# boot clock = alpha + beta * QPC, under the arrivals: beta from the run's two halves' lowest points, alpha so that the
# quickest 0.5% of frames have their data read 0.1 ms after the ACK reaches the PC
n = len(chain)
h1, h2 = chain[:n // 2], chain[n // 2:]
lo = lambda part: min(part, key=lambda c: c[4] - c[3])
p1, p2 = lo(h1), lo(h2)
beta = (p2[4] - p1[4]) / (p2[3] - p1[3])
res = sorted(c[4] - beta * c[3] for c in chain)
alpha = res[int(0.005 * n)] - 0.0001
toq = lambda boot: (boot - alpha) / beta
print('race: %d video frames matched to PC bursts; headset clock rate %+.1f ppm against the PC' % (n, 1e6 * (beta - 1)))
per = statistics.median([y[0] - x[0] for x, y in zip(chain, chain[1:])])


def grid_late(times):
    """each time against a steady grid through the earliest of the 60 around it (ms)"""
    res = []
    for i in range(len(times)):
        a, b = max(0, i - 30), min(len(times), i + 30)
        res.append(1e3 * (times[i] - min(times[j] - (j - i) * per for j in range(a, b))))
    return res


def pct(x, p):
    x = sorted(x); return x[min(len(x) - 1, int(p * len(x)))]


stages = {
    'capture T (vs grid)': grid_late([c[0] for c in chain]),
    'T to send start': [1e3 * (c[1] - c[0]) for c in chain],
    'send length': [1e3 * (c[2] - c[1]) for c in chain],
    'last segment to ACK': [1e3 * (c[3] - c[2]) for c in chain],
    'ACK to read by VD': [1e3 * (toq(c[4]) - c[3]) for c in chain],
    'decode (eye 1)': [1e3 * c[6] for c in chain],
    'decode (eye 2)': [1e3 * c[7] for c in chain],
    'T to both decoded': [1e3 * (toq(c[5]) - c[0]) for c in chain],
    'send start (vs grid)': grid_late([c[1] for c in chain]),
    'read by VD (vs grid)': grid_late([toq(c[4]) for c in chain]),
    'both decoded (vs grid)': grid_late([toq(c[5]) for c in chain]),
}
print('period %.3f ms; per stage (ms): median / 99%% / 99.9%% / max' % (1e3 * per))
for k, x in stages.items():
    print('  %-28s %6.2f %6.2f %6.2f %6.2f' % (k, pct(x, .5), pct(x, .99), pct(x, .999), max(x)))
sz = [c[8] / 1e3 for c in chain]
print('  %-28s %6.0f %6.0f %6.0f %6.0f' % ('frame size KB', pct(sz, .5), pct(sz, .99), pct(sz, .999), max(sz)))
with open(prefix + '_chain.csv', 'w') as o:
    o.write('T_qpc,send_start,send_end,ack,read_by_vd,decoded,decode_a_ms,decode_b_ms,bytes\n')
    for c in chain:
        o.write('%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%.3f,%.3f,%d\n' % (c[0], c[1], c[2], c[3], toq(c[4]), toq(c[5]), 1e3 * c[6], 1e3 * c[7], c[8]))

# the repeated frames: the video frame decoded last before the late app frame's xrEndFrame
lines = open(prefix + '_stale.csv').read().splitlines()
stale = [l.split(',') for l in lines[2:] if l]
fr = {}
for l in open(prefix + '_frames.csv').read().splitlines()[1:]:
    c = l.split(',')
    if c[5]:
        fr[int(c[0])] = float(c[5]) / 1e3
done = [c[5] for c in chain]
keys = list(stages)
print('\nrepeated frames in the race: the video frame VD waited for (ms; "vs grid": late against its neighbours)')
print('  %-9s %s %s' % ('race s', ' '.join('%7s' % k[:7] for k in keys), 'KB'))
for s in stale:
    e = fr.get(int(s[2]))
    if e is None or not A <= toq(e) <= B:
        continue
    i = bisect.bisect_right(done, e) - 1
    if i < 1:
        continue
    print('  %8.2f  %s %4.0f   decoded %.2f ms before xrEndFrame end' % (
        chain[i][0] - A + 3, ' '.join('%7.2f' % stages[k][i] for k in keys), chain[i][8] / 1e3, 1e3 * (e - chain[i][5])))
print('  %-9s %s' % ('median', ' '.join('%7.2f' % pct(stages[k], .5) for k in keys)))
