# Error Parsing — Multi-Provider Error Refinement

This document describes the `error_parsing` configuration mechanism that allows
the gateway and keeper to distinguish between different error types **within the
same HTTP status code** by inspecting the upstream response body.

For the core error classification system (`ErrorReason`, fatal/retryable/client
categories), see [docs/ERRORS.md](ERRORS.md).

---

## 1. Motivation

### 1.1. The HTTP Status Code Blind Spot

Most OpenAI-compatible providers return distinct HTTP status codes for distinct
error types:

| Error | HTTP | ErrorReason |
|-------|------|-------------|
| Invalid API key | 401 | `INVALID_KEY` |
| Account in arrears | 402 | `NO_QUOTA` |
| Rate limited | 429 | `RATE_LIMITED` |
| Bad request | 400 | `BAD_REQUEST` |
| Server error | 500 | `SERVER_ERROR` |

Some providers (notably Alibaba DashScope) use **HTTP 400 for everything**,
wrapping authentication failures, billing arrears, content safety blocks,
and parameter errors all behind the same status code:

| Error | HTTP | Body code | Correct ErrorReason |
|-------|------|-----------|---------------------|
| Billing arrears | 400 | `"Arrearage"` | `NO_QUOTA` |
| Invalid API key | 400 | `"InvalidApiKey"` | `INVALID_KEY` |
| Content safety | 400 | `"DataInspectionFailed"` | `BAD_REQUEST` |
| Bad parameters | 400 | `"InvalidParameter"` | `BAD_REQUEST` |
| Connection error | 400 | `"APIConnectionError"` | `NETWORK_ERROR` |

Without body inspection, the gateway maps ALL 400 responses to `BAD_REQUEST` (a
client error that does **not** penalise the key). This means billing arrears and
invalid keys would never be removed from rotation — a silent failure mode.

### 1.2. The Dual-Protocol Problem

Some providers offer **two API protocols** from the same `api_base_url`:

| Protocol | Endpoint | Error body structure |
|----------|----------|---------------------|
| OpenAI-compatible | `/compatible-mode/v1/chat/completions` | `{"error": {"code": "Arrearage", "message": "..."}}` |
| Native SDK | `/api/v1/services/aigc/text-generation/generation` | `{"code": "Arrearage", "message": "..."}` |

The transparent proxy does not inspect the request body, so both protocols can
flow through the same provider instance simultaneously. BUT the error response
formats differ: the OpenAI-compatible form nests fields under `"error"`, while
the native form places them at the JSON root.

A single set of error parsing rules using `error_path: "error.code"` will miss
all native-format errors because `_extract_json_value()` cannot find the
`"error"` key in the root object (it returns `None` → rule silently skipped).

**Solution: dual-format rules** — one set for the nested format, a second set
for the flat format. The two are naturally mutually exclusive: a response body
either has an `"error"` key or it doesn't.

---

## 2. How It Works

### 2.1. The Refinement Chain

```
HTTP response from upstream (e.g. 400)
  │
  ▼
_send_proxy_request()  [base.py:209]
  │
  ├─ body NOT read (zero-overhead):
  │    _parse_proxy_error(response, None)
  │    → _map_status_code_to_reason(400) → BAD_REQUEST
  │
  └─ body read (error_parsing enabled + rule matches status_code):
       _parse_proxy_error(response, bytes)
       → _map_status_code_to_reason(400) → BAD_REQUEST  (default)
       → _refine_error_reason(response, BAD_REQUEST, body_bytes)
            │
            ├─ No matching rules  → return BAD_REQUEST (unchanged)
            └─ Rule matched       → return rule.map_to  (e.g. NO_QUOTA)
```

The body is read only when at least one of these conditions is true:

1. `gateway_policy.debug_mode` is `"full_body"` or `"no_content"`, **OR**
2. `error_parsing.enabled` is `true` AND at least one `ErrorParsingRule` has a
   `status_code` matching the response.

Otherwise the **zero-overhead fast path** is taken — the body is never read, and
only the HTTP status code determines the error reason.

### 2.2. Value Passing with Multiple Rules

`_refine_error_reason()` collects **all** matching rules (not just the first),
then selects the one with the **highest priority**:

```python
# base.py:159-184
for rule in sorted(rules, key=lambda x: x.priority, reverse=True):
    if rule matches:
        matched_rules.append(rule)

if matched_rules:
    best_rule = max(matched_rules, key=lambda x: x.priority)
    return best_rule.map_to

return default_reason  # fallback if nothing matched
```

### 2.3. Dot-Path Extraction

`_extract_json_value()` (base.py:188-206) walks a JSON object by splitting the
`error_path` on `"."` and navigating the dict:

```python
_extract_json_value({"error": {"code": "Arrearage"}}, "error.code")
# → splits into ["error", "code"]
# → data["error"] → {"code": "Arrearage"}
# → ["code"] → "Arrearage"  ✅

_extract_json_value({"code": "Arrearage"}, "error.code")
# → splits into ["error", "code"]
# → "error" NOT in root dict → return None  ← rule skipped
```

It never raises exceptions on missing keys — it returns `None` cleanly.

### 2.4. Dot-Path vs Fulltext Modes

| Mode | error_path | What it matches |
|------|-----------|-----------------|
| **Dot-path** | e.g. `"error.code"`, `"error.message"`, `"code"` | Extracts a JSON value at the given path, applies `match_pattern` regex against the string form |
| **Fulltext** | `"$"` or `""` | Applies `match_pattern` regex against the entire raw response body (UTF-8 decoded) |

Fulltext mode is useful for catch-all rules or when the JSON structure varies
between response types. Note: `re.search(".*", text)` matches **any** string,
including empty strings — it is an effective "always match" catch-all.

### 2.5. Truthiness Guard

The dot-path branch has a truthiness guard (base.py:173):

```python
if value and re.search(rule.match_pattern, str(value), re.IGNORECASE):
```

If the extracted value is `None`, `0`, `False`, or `""`, the rule is silently
skipped — even if the regex would theoretically match. The fulltext branch
does **not** have this guard.

### 2.6. Priority Validation

Pydantic validates that all rules within the same `status_code` have unique
priorities (schemas.py:443-456). A config with duplicate priorities will fail
at load time with a clear error message.

---

## 3. Dual-Format Configuration Pattern

### 3.1. When to Use

Use this pattern when a single provider instance handles traffic from **two
different error body formats** — for example, DashScope where the transparent
proxy passes through both OpenAI-compatible requests (nested `"error"` format)
and native SDK requests (flat format).

### 3.2. The Pattern

Duplicate each error-type rule with the alternative `error_path`:

```yaml
error_parsing:
  enabled: true
  rules:
    # --- OpenAI-compatible (nested under "error") ---
    - status_code: 400
      error_path: "error.code"
      match_pattern: "Arrearage"
      map_to: "no_quota"
      priority: 100

    - status_code: 400
      error_path: "error.code"
      match_pattern: "InvalidApiKey"
      map_to: "invalid_key"
      priority: 90

    # --- DashScope native (flat, at root level) ---
    - status_code: 400
      error_path: "code"
      match_pattern: "Arrearage"
      map_to: "no_quota"
      priority: 95

    - status_code: 400
      error_path: "code"
      match_pattern: "InvalidApiKey"
      map_to: "invalid_key"
      priority: 85

    # Catch-all for unmatched 400 errors
    - status_code: 400
      error_path: "$"
      match_pattern: ".*"
      map_to: "bad_request"
      priority: 0
```

The two sets are **naturally mutually exclusive**: a JSON body with
`{"error": {"code": "Arrearage"}}` has no `"code"` at root level (the native
rule returns `None` and is skipped), and a body with `{"code": "Arrearage"}`
has no `"error"` key (the OpenAI-compatible rule returns `None`).

The slightly lower priorities for the native rules (95 vs 100, etc.) are a
safety measure — not strictly required, but ensures predictable ordering if
both formats somehow coexist in a single response.

### 3.3. Fallback Behaviour

If no rule matches a 400 response:
- **Gateway:** `_map_status_code_to_reason(400)` → `BAD_REQUEST` → treated as
  client error, key **NOT penalised**, no retries.
- **Keeper:** `_map_status_code_to_reason(400)` → `BAD_REQUEST` → soft penalty
  (`on_other_error_hr`, default 1 hour).

The catch-all rule (`error_path: "$"`, `match_pattern: ".*"`, `map_to: "bad_request"`,
`priority: 0`) makes this fallback explicit and auditable — without it, the
`default_reason` from the provider's status-code mapper would take effect,
producing the same end result but less transparently.

---

## 4. Keeper-Specific Behaviour

### 4.1. The 400 → INVALID_KEY Override

The Keeper (`check()` method in openai_like.py:226-232) has a special override:

```python
if status_code == 400:
    reason = ErrorReason.INVALID_KEY  # hard override before refinement
```

This exists because the Keeper sends a **pre-determined, known-correct** test
payload. A 400 response to a known-good request strongly suggests the key itself
is bad.

### 4.2. Refinement Runs AFTER the Override

Critically, `_refine_error_reason()` is called **after** the override (line 236):

```python
refined = await self._refine_error_reason(response, reason, body_bytes=text.encode())
```

This means error parsing rules can **correct** an over-aggressive
`400 → INVALID_KEY` classification. For example, a DashScope 400 with body
`{"code": "Arrearage"}` would initially be classified as `INVALID_KEY`, but a
rule matching `"Arrearage" → NO_QUOTA` would reclassify it correctly — the key
gets banned for quota reasons instead of being treated as an invalid key.

### 4.3. Keeper Endpoint and Error Format

The Keeper performs health checks against the URL defined by `endpoint_suffix`
in `default_model`. If this points to the **OpenAI-compatible** endpoint
(`/compatible-mode/v1/chat/completions`), the Keeper only ever sees
OpenAI-formatted errors — the `error.code` rules are sufficient.

If `endpoint_suffix` is later changed to a native SDK endpoint, the
dual-format rules will handle native-format errors correctly because
`_refine_error_reason()` runs against the actual response body, regardless
of which endpoint produced it.

---

## 5. What the Client Receives

The error parsing mechanism only affects the **internal `ErrorReason`
classification** used for key penalisation and retry decisions. It does
**not** modify the response sent to the HTTP client.

The client always receives:

- **The exact HTTP status code** from the upstream provider
- **The exact response body** (raw bytes, never filtered or modified)
- **Filtered response headers** (hop-by-hop headers like `transfer-encoding`,
  `connection`, `content-length` are stripped)

`CheckResult.message` stores the full raw body text (not an extracted JSON
field) and is used for logging and the `error_message` database column
(truncated to 1000 characters).

---

## 6. Interaction with Gateway Retry Policy

When `error_parsing` reclassifies an error, it changes the gateway's retry
behaviour:

| Refined ErrorReason | Retry? | Key penalised? |
|---------------------|--------|---------------|
| `NO_QUOTA`, `INVALID_KEY`, `NO_ACCESS` (fatal) | Yes — rotate to **next key** | Yes |
| `NETWORK_ERROR`, `RATE_LIMITED`, `SERVER_ERROR` (retryable) | Yes — retry **same key** first | After server retries exhausted |
| `BAD_REQUEST` (client error) | **No** — abort immediately | **No** |

Without error parsing, a DashScope `Arrearage` (HTTP 400) would:
1. Map to `BAD_REQUEST` → no retry, no key penalty
2. The key stays in the pool, continues to fail

With error parsing:
1. Refined to `NO_QUOTA` → key penalised, retry with next key
2. Client still gets the original 400 + body (transparent forwarding)

---

## 7. Configuration Schema

### ErrorParsingConfig

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | `bool` | `false` | Master switch for body-reading-based error refinement |
| `rules` | `list[ErrorParsingRule]` | `[]` | Ordered list of refinement rules |

### ErrorParsingRule

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `status_code` | `int` | **required** | HTTP status code this rule applies to (400–599) |
| `error_path` | `str` | **required** | JSON dot-path (`"error.code"`) or `"$"` for fulltext |
| `match_pattern` | `str` | **required** | Regex pattern (compiled at config load; invalid regex fails validation) |
| `map_to` | `ErrorReason` | **required** | ErrorReason to map to when this rule matches |
| `priority` | `int` | `0` | Higher = checked earlier and wins over lower-priority matches |
| `description` | `str` | `""` | Human-readable description of what this rule detects |

Constraints:
- `status_code`: must be 400 ≤ x < 600
- `priority`: must be ≥ 0, must be unique within the same `status_code`
- `match_pattern`: must be a valid Python regex
- `map_to`: must be a valid `ErrorReason` enum member

---

## 8. Complete Example

See `config/example_full_config.yaml`, Example 4 (`qwen-home`) for a full
dual-format configuration with in-line documentation explaining the mechanism.
