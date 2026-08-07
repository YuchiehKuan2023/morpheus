"""
Unit tests for environment_utils.py module.
Tests device detection and system information utilities.
"""

import sys
from pathlib import Path

import pytest

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from modules.utils.environment_utils import (
    check_memory_available,
    get_cpu_info,
    get_device,
    get_memory_info,
    get_platform_info,
    get_pytorch_info,
    is_apple_silicon,
    is_arm_architecture,
)


class TestDeviceDetection:
    """Test device detection functions."""

    def test_get_device_returns_string(self):
        """Test get_device returns a valid device string."""
        device = get_device()
        assert isinstance(device, str)
        assert device in ["cpu", "cuda", "mps"]

    def test_get_device_prefer_gpu_false(self):
        """Test get_device with prefer_gpu=False returns CPU."""
        device = get_device(prefer_gpu=False)
        assert device == "cpu"

    def test_get_device_prefer_gpu_true(self):
        """Test get_device with prefer_gpu=True."""
        device = get_device(prefer_gpu=True)
        # Should return best available device
        assert device in ["cpu", "cuda", "mps"]


class TestPlatformInfo:
    """Test platform information functions."""

    def test_get_platform_info(self):
        """Test get_platform_info returns dict with required keys."""
        info = get_platform_info()

        assert isinstance(info, dict)
        assert "system" in info
        assert "machine" in info  # Changed from "platform" to "machine"
        assert "architecture" in info
        assert "python_version" in info

    def test_is_arm_architecture(self):
        """Test is_arm_architecture returns boolean."""
        result = is_arm_architecture()
        assert isinstance(result, bool)

    def test_is_apple_silicon(self):
        """Test is_apple_silicon returns boolean."""
        result = is_apple_silicon()
        assert isinstance(result, bool)


class TestSystemResources:
    """Test system resource functions."""

    def test_get_cpu_info(self):
        """Test get_cpu_info returns dict."""
        info = get_cpu_info()

        assert isinstance(info, dict)
        assert "logical_cores" in info  # Changed from "count"
        assert "physical_cores" in info  # Changed from "physical_count"
        assert info["logical_cores"] > 0

    def test_get_memory_info(self):
        """Test get_memory_info returns dict."""
        info = get_memory_info()

        assert isinstance(info, dict)
        assert "total" in info
        assert "available" in info
        assert "percent_used" in info
        assert info["total"] > 0

    def test_check_memory_available(self):
        """Test check_memory_available with small requirement."""
        # Check for 1MB - should always be available
        result = check_memory_available(1)
        assert isinstance(result, bool)
        assert result is True

    def test_check_memory_available_large(self):
        """Test check_memory_available with huge requirement."""
        # Check for 1PB - should not be available
        result = check_memory_available(1024 * 1024 * 1024)  # 1PB
        assert isinstance(result, bool)


class TestPyTorchInfo:
    """Test PyTorch information functions."""

    def test_get_pytorch_info(self):
        """Test get_pytorch_info returns dict."""
        info = get_pytorch_info()

        assert isinstance(info, dict)
        assert "version" in info
        assert "cuda_available" in info
        assert "cuda_version" in info or info["cuda_available"] is False
        assert isinstance(info["cuda_available"], bool)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
