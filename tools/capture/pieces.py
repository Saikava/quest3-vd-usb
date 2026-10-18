"""pieces.py <vd.pcapng>: the sizes of the pieces VD sends on its video connection (runs of full segments ended by a
short one: one send each), as a histogram."""
import struct, sys
from collections import Counter, defaultdict
data = open(sys.argv[1], 'rb').read()
pos = 0; segs = defaultdict(list); last = {}
while pos + 8 <= len(data):
    btype, blen = struct.unpack_from('<II', data, pos)
    if blen < 12: break
    if btype == 6:
        ifid, th, tl, cap, orig = struct.unpack_from('<IIIII', data, pos + 8)
        t = ((th << 32) | tl) * 1e-7
        p0 = pos + 28
        if cap >= 74 and data[p0+12:p0+14] == b'\x86\xdd' and data[p0+20] == 6:
            plen = struct.unpack_from('>H', data, p0 + 18)[0]
            sp, dp, seq, ack, off = struct.unpack_from('>HHIIB', data, p0 + 54)
            ln = plen - (off >> 4) * 4
            if 38800 <= sp < 38900 and ln > 0:
                sig = (sp, dp, seq, ln)
                if t - last.get(sig, -1) >= 0.0002:
                    segs[(sp, dp)].append((seq, ln))
                last[sig] = t
    pos += blen
key = max(segs, key=lambda k: len(segs[k]))
S = segs[key]
mss = Counter(l for _, l in S).most_common(1)[0][0]
hi = None; cur = 0; pieces = Counter()
for seq, ln in S:
    if hi is not None and ((seq - hi) & 0xffffffff) >= 0x7fffffff:
        continue  # a resend
    hi = seq + ln
    cur += ln
    if ln < mss:
        pieces[cur] += 1
        cur = 0
n = sum(pieces.values())
print('MSS %d, %d pieces; most common sizes:' % (mss, n))
for s, c in pieces.most_common(12):
    print('  %6d bytes: %d (%.1f%%)' % (s, c, 100 * c / n))
print('largest: %s' % sorted(pieces)[-5:])
print('pieces over 15200: %d' % sum(c for s, c in pieces.items() if s > 15200))
