# Error Handling and Classification

This document describes the standardized error types used within the LLM Gateway and how different system components (Worker, Gateway) interpret and handle them.

## 1. Standard Error Types (`ErrorReason`)

The system normalizes all upstream provider errors into a specific set of `ErrorReason` enums. This abstraction allows the Gateway and Worker to apply consistent logic regardless of the underlying provider (OpenAI, Gemini, DeepSeek, etc.).

| Error Reason | Typical HTTP Code | Description |
| :--- | :--- | :--- |
| **`INVALID_KEY`** | 401 | The API key is invalid, revoked, or expired. |
| **`NO_ACCESS`** | 403 | Access denied. Often due to region blocks, lack of permissions, or required payment setup not being completed. |
| **`NO_QUOTA`** | 429 / 402 | The account has run out of credits or quota (hard limit). |
| **`NO_MODEL`** | 404 | The requested model does not exist or access is restricted for this specific key. |
| **`RATE_LIMITED`** | 429 | Temporary rate limit exceeded (requests per minute/day). |
| **`SERVER_ERROR`** | 500 | Upstream provider internal server error. |
| **`OVERLOADED`** | 503 | The upstream service is currently overloaded. |
| **`SERVICE_UNAVAILABLE`**| 503 | Upstream service maintenance or outage. |
| **`TIMEOUT`** | 504 | The request timed out (connection or read). |
| **`NETWORK_ERROR`** | 502 | Failed to establish a connection to the provider. |
| **`BAD_REQUEST`** | 400 | The request payload was invalid or rejected by the provider validation. |
| **`UNKNOWN`** | - | Unclassified error. |

---

## 2. Background Worker ("The Keeper")

The Background Worker's job is to validate API keys proactively. It classifies errors into three distinct categories to decide whether to ban a key, retry the check, or temporarily pause it.

This logic is defined in `src/services/probes/key_probe.py` and configured via `worker_health_policy`.

### 2.1. Fatal Errors (Key Killers)
**Errors**: `INVALID_KEY`, `NO_ACCESS`, `NO_QUOTA`, `NO_MODEL`

These errors indicate that the key is fundamentally unusable. Retrying immediately will not fix the issue.

*   **Behavior (Fast Fail)**: The worker **immediately** marks the key as failed. No verification retries are attempted.
*   **Penalty**: The key is disabled for a long duration (Days).
*   **Configuration Mapping**:
    *   `INVALID_KEY` -> `on_invalid_key_days` (default: 10 days)
    *   `NO_ACCESS` -> `on_no_access_days` (default: 10 days)
    *   `NO_QUOTA` -> `on_no_quota_hr` (default: 4 hours - shorter because users might top up credits)

### 2.2. Retryable Errors (Transient)
**Errors**: `RATE_LIMITED`, `SERVER_ERROR`, `TIMEOUT`, `NETWORK_ERROR`, `OVERLOADED`, `SERVICE_UNAVAILABLE`

These errors are temporary. The key is likely valid, but the environment or provider is unstable.

*   **Behavior (Verification Loop)**:
    1.  The worker detects a retryable error.
    2.  It enters a **Verification Loop**:
        *   Wait for `verification_delay_sec` (default: 65s, to clear minute-limit counters).
        *   Retry the request.
        *   Repeat up to `verification_attempts` (default: 3).
    3.  **Outcome**:
        *   **Success (200 OK)**: The key is marked `valid`. The error was a fluke.
        *   **Failure**: If all attempts fail, the key receives a temporary penalty.
*   **Penalty**: The key is paused for a short/medium duration (Minutes/Hours).
*   **Configuration Mapping**:
    *   `RATE_LIMITED` -> `on_rate_limit_hr` (default: 1 hour)
    *   `SERVER_ERROR` / `TIMEOUT` -> `on_server_error_min` (default: 30 mins)
    *   `OVERLOADED` -> `on_overload_min` (default: 60 mins)

### 2.3. Other Errors (Soft Failures)
**Errors**: `BAD_REQUEST`, `UNKNOWN`

These errors are ambiguous. `BAD_REQUEST` (400) typically implies the Worker sent a malformed payload (probe configuration issue) or the Provider rejected a specific parameter.

*   **Behavior**:
    *   **No Verification**: The Worker does *not* retry these errors. Retrying the same "bad" payload will just result in another 400 error.
    *   **Soft Penalty**: The key is marked as failed, but for a relatively short duration to allow for configuration fixes or transient provider validation glitches.
*   **Penalty**: Short duration (Hours).
*   **Configuration Mapping**:
    *   `BAD_REQUEST` / `UNKNOWN` -> `on_other_error_hr` (default: 1 hour)

---

## 3. Gateway Behavior

*(Section to be documented. Will cover real-time traffic handling, circuit breakers, and proxying logic)*
