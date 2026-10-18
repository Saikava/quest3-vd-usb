"""loadtest.py <seconds> <mbps> [label]: a steady TCP stream from the PC to the headset over the USB network
(VD's NCM link), like VD's video, to catch the link's freezes without the game (and without VD's own traffic).
The headset receives with toybox nc into /dev/null. The PC sends a chunk every millisecond; a send() that
blocks means the link (or the headset) stopped taking data. Run with netfreeze.py alongside for the headset's
view. Prints the stalls of the sender (>= 50 ms) and a summary line."""
import os
import socket
import subprocess
import sys
import time

seconds, mbps = float(sys.argv[1]), float(sys.argv[2])
period = float(sys.argv[4]) / 1000 if len(sys.argv) > 4 else 0.001  # one chunk per period (a burst)
label = sys.argv[3] if len(sys.argv) > 3 else 'load'
ADB = os.environ.get('ADB', 'adb')   # the adb executable (Android SDK platform-tools)
PORT = 5555


def headset_addr():
    out = subprocess.run([ADB, 'shell', 'ip -6 addr show usb0'], capture_output=True, text=True).stdout
    for w in out.split():
        if w.startswith('fe80::'):
            return w.split('/')[0]
    raise SystemExit('no usb0 address')


def pc_scope():
    out = subprocess.run(['powershell', '-NoProfile', '-Command',
                          "(Get-NetAdapter | Where-Object InterfaceDescription -match 'UsbNcm').ifIndex"],
                         capture_output=True, text=True).stdout.strip()
    return int(out.splitlines()[0])


addr, scope = headset_addr(), pc_scope()
nc = subprocess.Popen([ADB, 'shell', 'toybox nc -6 -l -p %d > /dev/null' % PORT])
time.sleep(1.0)
s = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
s.connect((addr, PORT, 0, scope))
chunk = bytes(int(mbps * 1e6 / 8 * period))  # per period
t0 = time.perf_counter()
stop = t0 + seconds
stalls = []
sent = 0
next_t = t0
while True:
    now = time.perf_counter()
    if now >= stop:
        break
    if now < next_t:
        continue  # busy wait: keeps the pacing to the millisecond
    a = time.perf_counter()
    s.sendall(chunk)
    b = time.perf_counter()
    sent += len(chunk)
    if b - a >= 0.05:
        stalls.append((a - t0, b - a))
    next_t += period
    if b > next_t + 0.05:
        next_t = b  # do not burst to catch up after a stall
s.close()
nc.kill()
span = time.perf_counter() - t0
print('%s: %.0f s at %.0f Mbit/s asked, %.0f Mbit/s sent, %d sender stalls >= 50 ms (%.1f per minute)%s' % (
    label, span, mbps, sent * 8 / span / 1e6, len(stalls), 60 * len(stalls) / span,
    ''.join('\n  at %+.2f s: blocked %.0f ms' % (t, 1000 * d) for t, d in stalls)))
