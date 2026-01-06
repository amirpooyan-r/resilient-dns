# ResilientDNS Relay (v0.7.0)

## 1. Overview

The ResilientDNS relay is an explicit upstream transport adapter. It accepts
DNS wire queries and returns DNS wire responses using a stateless HTTPS JSON
batch API. The relay is designed for unreliable, low-bandwidth, and
high-latency networks, and is intended to run on free-tier serverless platforms.

The Relay is a stateless HTTP batch DNS forwarder. It is NOT a router, default
gateway, NAT, or VPN gateway.

The relay is NOT:
- Automatic fallback
- Heuristic routing
- Censorship bypass logic
- DoH/DoT support inside ResilientDNS itself

## 2. Transport & Security

The relay URL is a full URL and MAY be HTTP or HTTPS. HTTPS is RECOMMENDED for
any non-local deployment.

Authentication uses an HTTP header:

```
Authorization: Bearer <token>
```

Authentication is OPTIONAL but STRONGLY RECOMMENDED. Authentication failures map
to explicit error handling defined in this document.

Endpoint paths are encrypted when using HTTPS. Authorization credentials MUST be
sent via headers only. JSON bodies MUST NOT contain secrets.

Relays SHOULD avoid logging decoded DNS payloads.

## 3. Endpoints

Endpoints use versioned REST-style paths. The integer API version is represented
as `n` in `/v{n}`.

All relay implementations MUST expose these paths for protocol v=1:

- POST /v{n}/dns
  - Handles all runtime DNS query traffic
  - Accepts JSON batch requests as defined below
  - Returns JSON batch responses as defined below
  - Optional gzip support remains unchanged

- GET /v{n}/info
  - Used ONLY for startup validation and diagnostics
  - MUST NOT be used on the runtime DNS query path
  - Safe to call once at startup
  - Stateless and cacheable

Requests to other paths SHOULD return HTTP 404.

### 3.1 Client Configuration Convention (Recommended)

ResilientDNS SHOULD be configured with:
- relay_base_url: a base HTTPS URL, optionally including a path prefix
- relay_api_version: integer (default 1)

Examples of `relay_base_url`:

- https://example.com
- https://example.com/gw
- https://example.workers.dev

Deterministic URL construction:

Let BASE = relay_base_url with any trailing slash removed.
Let V = relay_api_version.

- DNS URL  = BASE + "/v" + V + "/dns"
- INFO URL = BASE + "/v" + V + "/info"

Examples:

- BASE=https://example.com, V=1 -> /v1/dns and /v1/info
- BASE=https://example.com/gw, V=2 -> /gw/v2/dns and /gw/v2/info

### 3.2 /v1/info Response Schema

Example response:

```json
{
  "v": 1,
  "limits": {
    "max_items": 32,
    "max_request_bytes": 65536,
    "per_item_max_wire_bytes": 4096,
    "max_response_bytes": 262144
  },
  "auth_required": true
}
```

Rules:
- v is an integer protocol version
- limits MUST reflect enforced relay limits
- auth_required indicates whether Authorization is mandatory
- No secrets MUST be returned
- No state or persistence required

### 3.3 Startup Check Behavior (Non-Normative Guidance)

When relay mode is enabled, clients MAY call GET /v{n}/info once at startup.
Validation is OPTIONAL but RECOMMENDED for user-facing deployments. For
home/small office UX, clients SHOULD validate HTTP reachability, protocol
version (v == 1 for this spec), auth acceptance (401/403 means misconfigured
token), and advertised limits if provided. Startup checks are control-plane
only; runtime queries always use POST /v{n}/dns.

Clients MUST use the same path version for /info as for /dns. Clients MUST NOT
probe multiple versions by default. Startup checks MUST NOT affect runtime
determinism, and relays MUST remain stateless regardless of validation.

## 4. Request Format (JSON, versioned)

- Method: POST
- Content-Type: application/json
- Accept: application/json

Optional compression:
- Client MAY send: Content-Encoding: gzip
- Client MAY send: Accept-Encoding: gzip
- Relay MAY respond with: Content-Encoding: gzip
- Relay MUST always accept uncompressed JSON
- Unknown or nested encodings MUST be rejected

JSON schema (v = integer):

```json
{
  "v": 1,
  "id": "<client-generated request id>",
  "items": [
    { "id": "<item-id>", "q": "<base64 DNS wire query>" }
  ],
  "meta": {
    "client": "resilientdns",
    "client_version": "0.7.x",
    "tag": "<optional low-cardinality tag>"
  }
}
```

Rules:
- v MUST be integer
- id is echoed back in response
- items length MUST be <= relay_max_items
- Unknown fields MUST be ignored
- Base64 MUST decode to valid DNS wire bytes

## 5. Response Format (JSON)

- Content-Type: application/json
- Optional gzip compression (same rules as request)

JSON schema:

```json
{
  "v": 1,
  "id": "<echoed request id>",
  "items": [
    { "id": "<item-id>", "ok": true, "a": "<base64 DNS wire response>" },
    { "id": "<item-id>", "ok": false, "err": "<error-code>" }
  ]
}
```

Rules:
- Always return HTTP 200 for valid batch requests
- Partial success is allowed and expected
- Each item MUST contain either:
  - ok=true + a
  - ok=false + err

## 6. Error Codes (Fixed Enum)

Per-item errors are a fixed enum with no free-form strings:

- bad_request: The item is malformed or violates required schema.
- unauthorized: Authentication failed or is missing when required.
- too_large: Request, response, or item exceeds a configured limit.
- timeout: Upstream did not respond before the client deadline.
- upstream_error: Upstream resolver returned an error or failed.
- protocol_error: Non-compliant relay response or invalid DNS wire bytes.
- internal_error: Relay failed internally without a specific cause.
- rate_limited: Relay rejected the item due to rate limiting.

## 7. HTTP Status Handling

ResilientDNS interprets HTTP responses as follows:

- 200: parse JSON response
- 401 / 403: authentication error (unauthorized)
- other 4xx: bad_request
- 5xx: upstream_error
- Network failure / timeout: timeout

## 8. Determinism & Limits (MANDATORY)

Defaults:
- relay_max_items = 32
- relay_max_request_bytes = 64 KB (after decompression)
- relay_per_item_max_wire_bytes = 4096
- relay_max_response_bytes = 256 KB (after decompression)

Rules:
- If items.length > max_items, the entire request is rejected
- Request/response size limits are enforced AFTER decompression
- Per-item limits are enforced independently
- No retries
- No queueing
- Fail-fast behavior

## 9. Execution Model

The relay processes items with bounded internal concurrency. Concurrency is
implementation-defined but MUST be bounded. Sequential processing or small fixed
parallelism is RECOMMENDED. The relay MUST remain stateless.

## 10. Timeout Semantics

Client-side timeout is per-request (entire batch). If the timeout expires,
incomplete items return timeout. No per-item timeout is required in v0.7.0.

## 11. Metrics (Client-Side Only)

ResilientDNS SHOULD expose relay-related metrics, including:

- upstream_relay_requests_total
- upstream_relay_errors_total
- upstream_relay_timeouts_total
- upstream_relay_http_4xx_total
- upstream_relay_http_5xx_total
- upstream_relay_protocol_errors_total

Relay-side metrics are optional and not required by this spec.

## 12. Logging & Privacy

Relay implementations SHOULD avoid logging:
- decoded DNS query names
- raw DNS payloads

If logging is enabled, logs SHOULD be minimal and redacted. This is guidance,
not a requirement.

## 13. Compatibility with Serverless Free Tiers

- No persistent storage required
- No session state
- Suitable for Cloudflare Workers, Netlify, Vercel, and Deno Deploy
- All state carried in request/response

## 14. Versioning & Future Extensions

Path versioning (/v1/...) is the API convention. JSON field "v" is the protocol
version. The two are related but distinct. Future protocol versions may use:

- /v2/dns
- /v2/info

For v2, the relay would expose /v2/dns and /v2/info and would likely bump "v"
if the protocol changes. Relays SHOULD return HTTP 404 for unsupported path
versions. Clients MUST NOT assume backward compatibility across path versions.

ResilientDNS v0.7.0 defines JSON batch protocol v=1. Future versions MAY:
- add CBOR encoding
- add batch hints
- add request signing

Unknown fields MUST be ignored for forward compatibility.

## 15. Non-Goals (Explicit)

- No DoH/DoT support in ResilientDNS core
- No automatic fallback
- No retry heuristics
- No adaptive routing
- No censorship bypass logic
