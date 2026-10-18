"""ntbsweep.py <seconds per size> <size> ...: does a send of one particular size get lost over the USB network?
VD's lost blocks are all one send of 11 full segments and a short one (15200 bytes with VD's timestamps). Here the
PC sends one block of each given size every 2 ms (TCP_NODELAY: each send goes out as its own run of segments)
to toybox nc on the headset, a few seconds per size, and counts the PC's TCP retransmissions and the sender's
stalls (a send blocked over 50 ms: a loss that waited for the 300 ms timeout)."""
import ctypes
import os
import socket
import subprocess
import sys
import time

ADB = os.environ.get('ADB', 'adb')   # the adb executable (Android SDK platform-tools)
PORT = 5557
secs = float(sys.argv[1])
sizes = [int(x) for x in sys.argv[2:]]


class S(ctypes.Structure):
    _fields_ = [(n, ctypes.c_ulong) for n in 'a b c d e f g h i InSegs OutSegs RetransSegs InErrs OutRsts NumConns'.split()]


def retrans():
    s = S()
    ctypes.windll.iphlpapi.GetTcpStatisticsEx(ctypes.byref(s), 23)
    return s.RetransSegs


out = subprocess.run([ADB, 'shell', 'ip -6 addr show usb0'], capture_output=True, text=True).stdout
addr = next(w.split('/')[0] for w in out.split() if w.startswith('fe80::'))
scope = int(subprocess.run(['powershell', '-NoProfile', '-Command',
                            "(Get-NetAdapter | Where-Object InterfaceDescription -match 'UsbNcm').ifIndex"],
                           capture_output=True, text=True).stdout.split()[0])
nc = subprocess.Popen([ADB, 'shell', 'toybox nc -6 -l -p %d > /dev/null' % PORT])
time.sleep(1.0)
s = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
s.connect((addr, PORT, 0, scope))
for size in sizes:
    block = bytes(size)
    r0 = retrans()
    t0 = time.perf_counter()
    nxt = t0
    stalls = []
    n = 0
    while time.perf_counter() - t0 < secs:
        while time.perf_counter() < nxt:
            pass
        a = time.perf_counter()
        s.sendall(block)
        b = time.perf_counter()
        n += 1
        if b - a > 0.05:
            stalls.append(b - a)
        nxt = max(nxt + 0.002, b)
    span = time.perf_counter() - t0
    print('%5d bytes: %d sends, %d retransmissions (%.1f/s), %d stalls%s' % (
        size, n, retrans() - r0, (retrans() - r0) / span, len(stalls),
        (' (' + ', '.join('%.0f ms' % (1e3 * x) for x in stalls[:6]) + ')') if stalls else ''), flush=True)
s.close()
nc.kill()
