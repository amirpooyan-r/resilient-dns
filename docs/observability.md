# Observability

ResilientDNS follows a "logs first" approach: logs are the primary tool for
debugging behavior and verifying upstream failures, while counters provide a
low-overhead view of trends.

## Metrics Counters

- `queries_total`: Total DNS queries handled by the resolver.
- `cache_hit_fresh_total`: Count of responses served from fresh cache entries.
- `cache_hit_stale_total`: Count of responses served from stale cache entries.
- `cache_miss_total`: Count of cache misses that trigger upstream resolution.
- `negative_cache_hit_total`: Count of negative cached responses served.
- `upstream_requests_total`: Count of upstream DNS requests issued.
- `upstream_fail_total`: Count of upstream errors or timeouts.
- `swr_refresh_triggered_total`: Count of SWR refresh attempts started.
- `singleflight_dedup_total`: Count of requests deduplicated by SingleFlight.

`cache_hit_stale_total` includes both stale responses served immediately from
cache and "late stale" responses served after an upstream timeout or error.
