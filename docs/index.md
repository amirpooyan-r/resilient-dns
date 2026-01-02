# ResilientDNS

ResilientDNS is an open-source DNS cache and forwarder optimized for **unreliable, high-latency, and low-quality networks**.

It accepts standard DNS (UDP/TCP) from LAN devices and forwards misses through a **batched HTTPS gateway** designed to work reliably without depending on HTTP/2.

## What problem does it solve?

Many environments suffer from:
- Unstable UDP/TCP DNS resolution
- DNS hijacking/tampering risk
- Slow or unreliable HTTPS connectivity
- Legacy devices that cannot use DoH directly
- Upstream DoH setups that generate too many HTTPS requests (aggressive prefetch)

ResilientDNS focuses on correctness and resilience while minimizing upstream HTTPS traffic.

## Key features (planned)

- TTL-aware positive caching and negative caching
- Serve-stale behavior for resilience
- Adaptive, budgeted prefetch for hot domains
- Upstream request deduplication and batching
- HTTP/1.1-friendly gateway communication

## Status

🚧 Early development (MVP phase)

## Repository

- Source: GitHub repo (see top-right)
- Docs: This MkDocs site (published via GitHub Pages)
