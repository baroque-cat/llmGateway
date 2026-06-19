"""HTTP/2 Connection Pool Fixes.

Backport of encode/httpcore#1088 and #1022 into the llmGateway project.
Uses subclassing (not monkey-patching) for architectural cleanliness.

Remove this package when:
1. encode/httpcore merges both #1022 and #1088, AND
2. The project upgrades to that httpcore version.
"""

from src.core.http2.transport import CapacityAwareHttp2Transport

__all__ = ["CapacityAwareHttp2Transport"]
