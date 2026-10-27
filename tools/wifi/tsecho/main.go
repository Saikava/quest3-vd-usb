// tsecho: headset side of the one-way link probe.
// UDP echo: every reply is the probe payload plus three int64 little-endian nanosecond times on the headset's
// CLOCK_REALTIME: kernel receive (SO_TIMESTAMPNS), user-space receive, and send. Each received probe's sequence
// number (first 8 bytes) and kernel receive time are appended to a log file, so a lost probe can be blamed on
// the way down (never logged) or the way up (logged, no reply). TCP: accepts load streams and discards them.
package main

import (
	"encoding/binary"
	"flag"
	"fmt"
	"io"
	"net"
	"os"
	"syscall"
	"time"
	"unsafe"
)

func main() {
	udpPort := flag.Int("u", 5562, "UDP echo port")
	tcpPort := flag.Int("t", 5561, "TCP sink port")
	logPath := flag.String("o", "/data/local/tmp/tsecho.bin", "received-probe log")
	framePort := flag.Int("f", 5563, "TCP frame-stream port")
	framePath := flag.String("fo", "/data/local/tmp/frames.bin", "received-frame log")
	flag.Parse()

	go func() {
		ln, err := net.Listen("tcp", fmt.Sprintf(":%d", *tcpPort))
		if err != nil {
			fmt.Fprintln(os.Stderr, "tcp:", err)
			return
		}
		for {
			c, err := ln.Accept()
			if err != nil {
				return
			}
			go func(c net.Conn) { io.Copy(io.Discard, c); c.Close() }(c)
		}
	}()

	// frame receiver: a VD-like video stream. Each frame is a 24-byte header (magic "VRF1", payload length u32,
	// sequence u64, sender time u64, all little-endian) followed by the payload. For every frame the headset logs
	// (sequence, first-byte time, last-byte time) on CLOCK_REALTIME to framePath.
	go func() {
		ln, err := net.Listen("tcp", fmt.Sprintf(":%d", *framePort))
		if err != nil {
			fmt.Fprintln(os.Stderr, "frames:", err)
			return
		}
		for {
			c, err := ln.Accept()
			if err != nil {
				return
			}
			go func(c net.Conn) {
				defer c.Close()
				f, err := os.Create(*framePath)
				if err != nil {
					return
				}
				defer f.Close()
				hdr := make([]byte, 24)
				body := make([]byte, 4<<20)
				rec := make([]byte, 24)
				for {
					if _, err := io.ReadFull(c, hdr[:1]); err != nil {
						return
					}
					first := time.Now().UnixNano()
					if _, err := io.ReadFull(c, hdr[1:]); err != nil {
						return
					}
					if string(hdr[0:4]) != "VRF1" {
						return
					}
					n := int(binary.LittleEndian.Uint32(hdr[4:8]))
					if n > len(body) {
						return
					}
					if _, err := io.ReadFull(c, body[:n]); err != nil {
						return
					}
					last := time.Now().UnixNano()
					copy(rec[0:8], hdr[8:16])
					binary.LittleEndian.PutUint64(rec[8:16], uint64(first))
					binary.LittleEndian.PutUint64(rec[16:24], uint64(last))
					f.Write(rec)
				}
			}(c)
		}
	}()

	conn, err := net.ListenUDP("udp", &net.UDPAddr{Port: *udpPort})
	if err != nil {
		fmt.Fprintln(os.Stderr, "udp:", err)
		os.Exit(1)
	}
	raw, _ := conn.SyscallConn()
	raw.Control(func(fd uintptr) {
		if err := syscall.SetsockoptInt(int(fd), syscall.SOL_SOCKET, syscall.SO_TIMESTAMPNS, 1); err != nil {
			fmt.Fprintln(os.Stderr, "SO_TIMESTAMPNS:", err)
		}
	})
	logf, err := os.Create(*logPath)
	if err != nil {
		fmt.Fprintln(os.Stderr, "log:", err)
		os.Exit(1)
	}
	fmt.Println("tsecho ready")

	buf := make([]byte, 2048)
	oob := make([]byte, 256)
	out := make([]byte, 2048)
	rec := make([]byte, 16)
	for {
		n, oobn, _, addr, err := conn.ReadMsgUDP(buf, oob)
		tu := time.Now().UnixNano()
		if err != nil {
			continue
		}
		var tk int64
		if msgs, err := syscall.ParseSocketControlMessage(oob[:oobn]); err == nil {
			for _, m := range msgs {
				if m.Header.Level == syscall.SOL_SOCKET && m.Header.Type == syscall.SCM_TIMESTAMPNS && len(m.Data) >= 16 {
					ts := (*syscall.Timespec)(unsafe.Pointer(&m.Data[0]))
					tk = ts.Nano()
				}
			}
		}
		copy(out, buf[:n])
		binary.LittleEndian.PutUint64(out[n:], uint64(tk))
		binary.LittleEndian.PutUint64(out[n+8:], uint64(tu))
		binary.LittleEndian.PutUint64(out[n+16:], uint64(time.Now().UnixNano()))
		conn.WriteToUDP(out[:n+24], addr)
		if n >= 8 {
			copy(rec[:8], buf[:8])
			binary.LittleEndian.PutUint64(rec[8:], uint64(tk))
			logf.Write(rec)
		}
	}
}
