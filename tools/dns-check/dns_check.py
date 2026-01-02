#!/usr/bin/env python3
import argparse
import socket
import time

from dnslib import DNSRecord


def send_query(
    server: str,
    port: int,
    name: str,
    qtype: str,
    timeout: float,
) -> tuple[float, DNSRecord]:
    try:
        query = DNSRecord.question(name, qtype)
    except Exception as e:
        raise ValueError(f"Unknown query type: {qtype}") from e

    wire = query.pack()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)

    start = time.perf_counter()
    sock.sendto(wire, (server, port))
    data, _ = sock.recvfrom(4096)
    elapsed = (time.perf_counter() - start) * 1000.0
    sock.close()

    return elapsed, DNSRecord.parse(data)


def main() -> None:
    parser = argparse.ArgumentParser(description="DNS check tool for ResilientDNS")
    parser.add_argument("name", help="Domain name (e.g. example.com)")
    parser.add_argument("-t", "--type", default="A", help="Query type (A, AAAA, TXT, etc.)")
    parser.add_argument("--server", default="127.0.0.1", help="DNS server address")
    parser.add_argument("--port", type=int, default=5353, help="DNS server port")
    parser.add_argument("--repeat", type=int, default=1, help="Repeat query N times")
    parser.add_argument("--timeout", type=float, default=2.0, help="Socket timeout (seconds)")
    args = parser.parse_args()

    qtype = args.type.upper()

    print(f"DNS check → {args.name} ({qtype})")
    print(f"Server: {args.server}:{args.port}")
    print("-" * 50)

    for i in range(args.repeat):
        try:
            latency_ms, response = send_query(
                args.server, args.port, args.name, qtype, args.timeout
            )
            rcode = response.header.rcode
            answers = len(response.rr)

            print(f"[{i + 1}] {latency_ms:7.2f} ms | rcode={rcode} | answers={answers}")
        except Exception as e:
            print(f"[{i + 1}] ERROR: {e}")


if __name__ == "__main__":
    main()
