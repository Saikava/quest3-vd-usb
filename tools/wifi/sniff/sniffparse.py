"""sniffparse.py <capture.pcap|pcapng> <out.bin>: radiotap 802.11 capture (macOS Wireless Diagnostics sniffer) to a
compact record file for sniffan.py. One record per captured MPDU:
pts_us (capture host time), tsft_us (MAC time, 0 if absent), fc, a1, a2 (indexes into the MAC table, 0xffff = none),
length, mcs, nss, bw MHz, sgi, signal dBm, ampdu ref, flags (1 = bad FCS), 802.11 sequence number (data and
management), BlockAck starting sequence number and bitmap (compressed BlockAck). MAC table goes to <out.bin>.macs."""
import mmap
import struct
import sys

REC = struct.Struct('<qqHHHHBBHBbIBHHQ')  # + seq number, BlockAck start seq, BlockAck bitmap
# radiotap fields of the first present word: bit -> (size, align)
SPEC = {0: (8, 8), 1: (1, 1), 2: (1, 1), 3: (4, 2), 4: (2, 1), 5: (1, 1), 6: (1, 1), 7: (2, 2), 8: (2, 2), 9: (2, 2),
        10: (1, 1), 11: (1, 1), 12: (1, 1), 13: (1, 1), 14: (2, 2), 15: (2, 2), 16: (1, 1), 17: (1, 1), 18: (8, 4),
        19: (3, 1), 20: (8, 4), 21: (12, 2), 22: (12, 8), 23: (12, 2), 24: (12, 2), 25: (6, 2), 26: (1, 1), 27: (4, 2)}
VHTBW = {0: 20, 1: 40, 2: 40, 3: 40, 4: 80}
for i in range(5, 11):
    VHTBW[i] = 80
for i in range(11, 26):
    VHTBW[i] = 160


def packets(m):
    magic = struct.unpack_from('<I', m, 0)[0]
    if magic in (0xa1b2c3d4, 0xa1b23c4d):
        ns = magic == 0xa1b23c4d
        lt = struct.unpack_from('<I', m, 20)[0]
        off = 24
        while off + 16 <= len(m):
            s, frac, incl, _ = struct.unpack_from('<IIII', m, off)
            yield lt, s * 1000000 + (frac // 1000 if ns else frac), off + 16, incl
            off += 16 + incl
    elif magic == 0x0a0d0d0a:
        off, lts, res = 0, [], []
        while off + 12 <= len(m):
            bt, bl = struct.unpack_from('<II', m, off)
            if bl < 12:
                break
            if bt == 1:
                lts.append(struct.unpack_from('<H', m, off + 8)[0])
                r, o = 1e-6, off + 16
                while o + 4 <= off + bl - 4:
                    code, ol = struct.unpack_from('<HH', m, o)
                    if code == 0:
                        break
                    if code == 9:
                        v = m[o + 4]
                        r = 2.0 ** -(v & 0x7f) if v & 0x80 else 10.0 ** -v
                    o += 4 + ((ol + 3) & ~3)
                res.append(r)
            elif bt == 6:
                iid, th, tl, cap = struct.unpack_from('<IIII', m, off + 8)
                t = (th << 32 | tl) * res[iid]
                yield lts[iid], int(t * 1e6), off + 28, cap
            off += bl
    else:
        sys.exit('unknown capture format %08x' % magic)


def main():
    src, dst = sys.argv[1], sys.argv[2]
    f = open(src, 'rb')
    m = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
    macs, mi = {}, {}

    def idx(a):
        i = mi.get(a)
        if i is None:
            i = mi[a] = len(macs)
            macs[i] = a
        return i
    out = open(dst, 'wb')
    n = bad = other = 0
    chans = {}
    for lt, pts, off, cap in packets(m):
        if lt != 127:
            other += 1
            continue
        rl = struct.unpack_from('<H', m, off + 2)[0]
        p = off + 4
        pres = []
        while True:
            w = struct.unpack_from('<I', m, p)[0]
            pres.append(w)
            p += 4
            if not w & 0x80000000:
                break
        w0 = pres[0]
        pos = p - off
        tsft, flags, mcs, nss, bw, sgi, sig, ref, freq = 0, 0, 255, 0, 20, 0, 0, 0, 0
        for bit in range(28):
            if not w0 & (1 << bit):
                continue
            size, al = SPEC[bit]
            pos = (pos + al - 1) & ~(al - 1)
            a = off + pos
            if bit == 0:
                tsft = struct.unpack_from('<Q', m, a)[0]
            elif bit == 1:
                flags = m[a]
            elif bit == 3:
                freq = struct.unpack_from('<H', m, a)[0]
            elif bit == 5:
                sig = struct.unpack_from('<b', m, a)[0]
            elif bit == 19:
                known, fl, mc = m[a], m[a + 1], m[a + 2]
                mcs, nss, bw, sgi = mc % 8, mc // 8 + 1, 40 if fl & 3 == 1 else 20, 1 if fl & 4 else 0
            elif bit == 20:
                ref = struct.unpack_from('<I', m, a)[0]
            elif bit == 21:
                fl, b = m[a + 2], m[a + 3]
                mn = m[a + 4]
                mcs, nss, bw, sgi = mn >> 4, mn & 15, VHTBW.get(b, 0), 1 if fl & 4 else 0
            pos += size
        chans[freq] = chans.get(freq, 0) + 1
        h = off + rl
        ln = cap - rl - (4 if flags & 0x10 else 0)
        if ln < 10:
            continue
        fc = m[h] | m[h + 1] << 8
        a1 = idx(bytes(m[h + 4:h + 10]))
        typ, sub = (fc >> 2) & 3, (fc >> 4) & 15
        a2 = 0xffff if (typ == 1 and sub in (12, 13)) or ln < 16 else idx(bytes(m[h + 10:h + 16]))
        fl = 1 if flags & 0x40 else 0
        bad += fl
        sq = ssn = bmp = 0
        if typ in (0, 2) and ln >= 24:
            sq = struct.unpack_from('<H', m, h + 22)[0] >> 4
        elif typ == 1 and sub == 9 and ln >= 28:
            ssn = struct.unpack_from('<H', m, h + 18)[0] >> 4
            bmp = struct.unpack_from('<Q', m, h + 20)[0]
        out.write(REC.pack(pts, tsft, fc, a1, a2, min(ln, 65535), min(mcs, 255), nss, bw, sgi, max(-128, min(127, sig)),
                           ref, fl, sq, ssn, bmp))
        n += 1
    out.close()
    with open(dst + '.macs', 'w') as g:
        for i in range(len(macs)):
            g.write(':'.join('%02x' % x for x in macs[i]) + '\n')
    print('records %d, bad FCS %d, non-radiotap %d, MACs %d, frequencies %s' % (n, bad, other, len(macs),
          sorted(chans.items(), key=lambda x: -x[1])[:5]))


main()
