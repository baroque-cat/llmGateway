#!/usr/bin/env python3

import pytest
from src.core.constants import ALL_MODELS_MARKER


def test_constants_defined():
    """Verify the ALL_MODELS_MARKER constant is defined correctly."""
    assert ALL_MODELS_MARKER == "__ALL_MODELS__"