"""
Batching strategies for background worker resource probes.

The adaptive batch controller (``adaptive.py``) provides self-tuning
batch sizing and delay management based on check result statistics.
"""

from src.core.batching import AdaptiveBatchController

__all__ = ["AdaptiveBatchController"]
