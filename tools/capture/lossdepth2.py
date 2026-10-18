"""lossdepth2.py <vd.pcapng>: VD's losses on the video connection as episodes. A lost run of segments (sent again
over 1.5 ms after their first send: closer copies are the capture's duplicates) is one episode, and for each: when,
how long until the resend, the burst the hole was in (its size, and how much of it came after the hole), the next
bursts, how much the PC had sent beyond the hole by the resend. And the tail of the burst sizes, per minute."""
import bisect
import struct
import sys
from collections import defaultdict

data = open(sys.argv[1], 'rb').read()
pos = 0
tsres = {}
nif = 0
segs = defaultdict(list)
bytes_by = defaultdict(int)
last = {}
while pos + 8 <= len(data):
    btype, blen = struct.unpack_from('<II', data, pos)
    if blen < 12:
        break
    if btype == 1:
        body = data[pos + 8:pos + blen - 4]
        tsres[nif] = 1e-6
        o = 8
        while o + 4 <= len(body):
            code, ln = struct.unpack_from('<HH', body, o)
            if code == 0:
                break
            if code == 9:
                v = body[o + 4]
                tsres[nif] = 2.0 ** -(v & 0x7f) if v & 0x80 else 10.0 ** -v
            o += 4 + ((ln + 3) & ~3)
        nif += 1
    elif btype == 6:
        ifid, th, tl, cap, orig = struct.unpack_from('<IIIII', data, pos + 8)
        t = ((th << 32) | tl) * tsres.get(ifid, 1e-6)
        p0 = pos + 28
        if cap >= 74 and data[p0 + 12:p0 + 14] == b'\x86\xdd' and data[p0 + 20] == 6:
            ip = p0 + 14
            plen = struct.unpack_from('>H', data, ip + 4)[0]
            tcp = ip + 40
            sp, dp, seq, ack, off = struct.unpack_from('>HHIIB', data, tcp)
            ln = plen - (off >> 4) * 4
            if 38800 <= sp < 38900 and ln > 0:
                sig = (sp, dp, seq, ln)
                if t - last.get(sig, -1) >= 0.0002:  # not the same packet seen twice
                    segs[(sp, dp)].append((t, seq, ln))
                    bytes_by[(sp, dp)] += ln
                last[sig] = t
    pos += blen

key = max(bytes_by, key=bytes_by.get)
S = segs[key]
T0 = S[0][0]
base = S[0][1]
span = S[-1][0] - T0

# bursts: segments less than 2 ms apart
bstart, bbytes, bidx = [], [], []
prev = None
for t, seq, ln in S:
    if prev is None or t - prev > 0.002:
        bstart.append(t)
        bbytes.append(0)
    bbytes[-1] += ln
    bidx.append(len(bstart) - 1)
    prev = t
nb = len(bstart)
print('video connection: %.0f Mbit/s over %.0f s, %d bursts (%.0f/s)' % (sum(bbytes) * 8 / span / 1e6, span, nb,
                                                                        nb / span))
for x in (150, 200, 250, 300, 350, 400, 500):
    n = sum(1 for b in bbytes if b > x * 1000)
    print('  bursts over %d KB: %d (%.1f per minute)' % (x, n, 60 * n / span))

first = {}
hi = 0
hi_t, hi_v = [], []
resends = []  # (t, rel seq, index of the first send)
r = 0
lastseq = base
for i, (t, seq, ln) in enumerate(S):
    # the sequence numbers unwrapped (a long capture of the video runs past 4 GB)
    d = (seq - lastseq) & 0xffffffff
    r += d - (1 << 32) if d >= 1 << 31 else d
    lastseq = seq
    if r in first and r + ln <= hi:
        if t - S[first[r]][0] > 0.0015:
            resends.append((t, r, first[r]))
    else:
        first.setdefault(r, i)
    hi = max(hi, r + ln)
    hi_t.append(t)
    hi_v.append(hi)

# episodes: resends within 20 ms of the episode's first resend
eps = []
for t, r, i in resends:
    if eps and t - eps[-1][0] < 0.02:
        e = eps[-1]
        e[1] = min(e[1], r)
        e[2] = min(e[2], i)
        e[3] += 1
    else:
        eps.append([t, r, i, 1])
print('loss episodes: %d (%.1f per minute)' % (len(eps), 60 * len(eps) / span))
print('   at s  resend ms  segs | hole burst KB, after the hole | next bursts KB (ms later) | KB beyond by the resend')
for t1, r, i, n in eps:
    t0 = S[i][0]
    b = bidx[i]
    after = sum(S[k][2] for k in range(i, len(S)) if bidx[k] == b and S[k][0] >= t0)
    nxt = ' '.join('%.0f(%+.0f)' % (bbytes[k] / 1e3, 1e3 * (bstart[k] - t0)) for k in range(b + 1, min(nb, b + 4))
                   if bstart[k] < t1 + 0.0005)
    j = bisect.bisect_left(hi_t, t1) - 1
    print('%7.2f %8.1f %5d | %6.0f %6.0f | %-32s | %4.0f%s' % (
        t0 - T0, 1e3 * (t1 - t0), n, bbytes[b] / 1e3, after / 1e3, nxt, (hi_v[j] - r) / 1e3,
        '   <== timeout' if t1 - t0 > 0.1 else ''))
