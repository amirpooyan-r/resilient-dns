# Roadmap

## MVP-1
- ✅ UDP DNS listener (port 5353 for dev)
- ✅ TTL-aware cache (positive + negative)
- ✅ Serve-stale (stale-if-error)
- ✅ Bounded cache eviction (expired-first, then LRU)
- ✅ Stale-while-revalidate (SWR)
- Remote batch relay client (HTTP/1.1 friendly)
- Cloudflare Worker relay starter

## MVP-2
- TCP support + truncation handling
- ✅ Single-flight deduplication
- Adaptive prefetch with budgets
- ✅ Lightweight metrics counters
- Basic metrics endpoint

## Later
- Additional relays (PHP, .NET, Node)
- Benchmark + trace tools
- Docker + CI hardening
