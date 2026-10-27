// framesink: tsecho's frame receiver for a laptop (macOS, Windows, Linux), as a second Wi-Fi client to compare with
// the headset. Same frame stream as tsecho (TCP 5563: "VRF1", payload length u32, sequence u64, sender time u64, then
// the payload; logs sequence, first-byte and last-byte wall-clock ns), and a plain UDP echo on 5562 for frameprobe's
// uplink probes (no kernel timestamps: SO_TIMESTAMPNS is Linux-only). Instead of adb pull, the PC reads the log of
// the last finished stream from TCP 5564. Runs until Ctrl+C.
package main

import (
	"encoding/binary"
	"flag"
	"fmt"
	"io"
	"net"
	"os"
	"sync"
	"time"
)

func main() {
	udpPort := flag.Int("u", 5562, "UDP echo port")
	framePort := flag.Int("f", 5563, "TCP frame-stream port")
	dumpPort := flag.Int("d", 5564, "TCP port that returns the last stream's log")
	addr := flag.String("a", "", "listen address (default: all)")
	flag.Parse()

	var mu sync.Mutex
	var last []byte // log of the last finished stream, 24 bytes per frame

	ln, err := net.Listen("tcp", fmt.Sprintf("%s:%d", *addr, *framePort))
	if err != nil {
		fmt.Fprintln(os.Stderr, "frames:", err)
		os.Exit(1)
	}
	go func() {
		for {
			c, err := ln.Accept()
			if err != nil {
				return
			}
			go func(c net.Conn) {
				defer c.Close()
				log := make([]byte, 0, 24*120*600)
				defer func() {
					mu.Lock()
					last = log
					mu.Unlock()
					fmt.Printf("stream from %s done: %d frames\n", c.RemoteAddr(), len(log)/24)
				}()
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
					lastByte := time.Now().UnixNano()
					copy(rec[0:8], hdr[8:16])
					binary.LittleEndian.PutUint64(rec[8:16], uint64(first))
					binary.LittleEndian.PutUint64(rec[16:24], uint64(lastByte))
					log = append(log, rec...)
				}
			}(c)
		}
	}()

	dl, err := net.Listen("tcp", fmt.Sprintf("%s:%d", *addr, *dumpPort))
	if err != nil {
		fmt.Fprintln(os.Stderr, "dump:", err)
		os.Exit(1)
	}
	go func() {
		for {
			c, err := dl.Accept()
			if err != nil {
				return
			}
			mu.Lock()
			b := last
			mu.Unlock()
			c.Write(b)
			c.Close()
		}
	}()

	conn, err := net.ListenUDP("udp", &net.UDPAddr{IP: net.ParseIP(*addr), Port: *udpPort})
	if err != nil {
		fmt.Fprintln(os.Stderr, "udp:", err)
		os.Exit(1)
	}
	fmt.Println("framesink ready")
	buf := make([]byte, 2048)
	out := make([]byte, 2048)
	for {
		n, addr, err := conn.ReadFromUDP(buf)
		tu := time.Now().UnixNano()
		if err != nil {
			continue
		}
		copy(out, buf[:n])
		binary.LittleEndian.PutUint64(out[n:], 0) // no kernel time
		binary.LittleEndian.PutUint64(out[n+8:], uint64(tu))
		binary.LittleEndian.PutUint64(out[n+16:], uint64(time.Now().UnixNano()))
		conn.WriteToUDP(out[:n+24], addr)
	}
}
