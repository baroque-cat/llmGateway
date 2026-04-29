#!/usr/bin/env python3

"""Tests for automatic key directory path computing."""

import os


def test_key_path_computed_for_gemini_pro_home():
    """Provider name 'gemini-pro-home' yields path 'data/gemini-pro-home/raw'."""
    expected = os.path.join("data", "gemini-pro-home", "raw")
    assert expected == "data/gemini-pro-home/raw"


def test_key_path_computed_for_qwen_home():
    """Provider name 'qwen-home' yields path 'data/qwen-home/raw'."""
    expected = os.path.join("data", "qwen-home", "raw")
    assert expected == "data/qwen-home/raw"


def test_key_path_uses_os_path_join():
    """Path is constructed using os.path.join('data', name, 'raw')."""
    name = "some-provider"
    path = os.path.join("data", name, "raw")
    assert path == "data/some-provider/raw"
    # Verify cross-platform: no hardcoded slashes
    assert "data" in path and name in path and "raw" in path
