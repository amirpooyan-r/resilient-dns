# Failure Modes

## Upstream Timeout or Error

- Upstream queries are bounded by a timeout; on timeout or error, the behavior below applies.
- If stale cache is available, ResilientDNS serves it immediately and schedules
  a background refresh.
- If no cache entry exists, ResilientDNS returns `SERVFAIL`.

## Refresh Behavior

Refresh failures do not block requests. They only affect logs and metrics, and
the resolver continues to serve cached responses when possible. Refresh is
best-effort with no retries or fallback.
