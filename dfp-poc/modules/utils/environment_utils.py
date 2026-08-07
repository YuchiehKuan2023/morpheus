"""
Environment detection and system utilities for DFP PoC.

This module provides utilities for detecting the execution environment,
including device detection (CPU, CUDA, MPS), platform information,
memory checks, and resource monitoring.

Reference:
    - NVIDIA Morpheus environment detection patterns
    - PyTorch device management
"""

import os
import platform
from typing import Any

import psutil
import torch


def get_device(prefer_gpu: bool = True) -> str:
    """
    Detect and return the best available computation device.

    Args:
        prefer_gpu: Whether to prefer GPU over CPU if available

    Returns:
        Device string: "cuda", "mps", or "cpu"

    Example:
        >>> device = get_device()
        >>> print(f"Using device: {device}")
        Using device: cpu
    """
    if not prefer_gpu:
        return "cpu"

    # Check for CUDA (NVIDIA GPU)
    if torch.cuda.is_available():
        return "cuda"

    # Check for MPS (Apple Silicon GPU - M1/M2/M3 Mac)
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        # Note: MPS is available but sometimes unstable, so we can add a check
        if os.environ.get("ENABLE_MPS", "false").lower() == "true":
            return "mps"

    # Default to CPU
    return "cpu"


def get_device_count() -> int:
    """
    Get the number of available CUDA devices.

    Returns:
        Number of CUDA GPUs available

    Example:
        >>> count = get_device_count()
        >>> print(f"Available GPUs: {count}")
        Available GPUs: 0
    """
    if torch.cuda.is_available():
        return torch.cuda.device_count()
    return 0


def get_device_name(device_id: int = 0) -> str:
    """
    Get the name of a specific CUDA device.

    Args:
        device_id: GPU device ID (0-indexed)

    Returns:
        Device name string

    Example:
        >>> name = get_device_name(0)
        >>> print(f"GPU: {name}")
        GPU: NVIDIA GeForce RTX 3090
    """
    if torch.cuda.is_available() and device_id < torch.cuda.device_count():
        return torch.cuda.get_device_name(device_id)
    return "N/A"


def get_device_memory(device_id: int = 0) -> tuple[int, int]:
    """
    Get total and available memory for a CUDA device.

    Args:
        device_id: GPU device ID (0-indexed)

    Returns:
        Tuple of (total_memory_bytes, free_memory_bytes)

    Example:
        >>> total, free = get_device_memory(0)
        >>> print(f"GPU Memory: {free / 1024**3:.1f} GB / {total / 1024**3:.1f} GB")
    """
    if torch.cuda.is_available() and device_id < torch.cuda.device_count():
        total = torch.cuda.get_device_properties(device_id).total_memory
        reserved = torch.cuda.memory_reserved(device_id)
        allocated = torch.cuda.memory_allocated(device_id)  # noqa: F841 - may be used for debugging
        free = total - reserved
        return (total, free)
    return (0, 0)


def get_platform_info() -> dict[str, str]:
    """
    Get detailed platform information.

    Returns:
        Dictionary containing platform details

    Example:
        >>> info = get_platform_info()
        >>> print(f"OS: {info['system']} {info['release']}")
        OS: Darwin 23.1.0
    """
    return {
        "system": platform.system(),  # 'Darwin', 'Linux', 'Windows'
        "release": platform.release(),  # OS release version
        "version": platform.version(),  # OS version string
        "machine": platform.machine(),  # 'arm64', 'x86_64', etc.
        "processor": platform.processor(),  # Processor name
        "architecture": platform.architecture()[0],  # '64bit', '32bit'
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
    }


def is_arm_architecture() -> bool:
    """
    Check if running on ARM architecture (e.g., M1/M2/M3 Mac).

    Returns:
        True if ARM architecture, False otherwise

    Example:
        >>> if is_arm_architecture():
        ...     print("Running on ARM processor (M1/M2/M3 Mac)")
    """
    machine = platform.machine().lower()
    return "arm" in machine or "aarch" in machine


def is_apple_silicon() -> bool:
    """
    Check if running on Apple Silicon (M1/M2/M3 Mac).

    Returns:
        True if Apple Silicon, False otherwise
    """
    return platform.system() == "Darwin" and is_arm_architecture()


def get_cpu_info() -> dict[str, Any]:
    """
    Get CPU information.

    Returns:
        Dictionary containing CPU details

    Example:
        >>> info = get_cpu_info()
        >>> print(f"CPU Cores: {info['physical_cores']} physical, {info['logical_cores']} logical")
    """
    try:
        cpu_freq = psutil.cpu_freq()
        current_freq = cpu_freq.current if cpu_freq else None
        max_freq = cpu_freq.max if cpu_freq else None
    except (AttributeError, NotImplementedError):
        # cpu_freq not available on some platforms (e.g., macOS)
        current_freq = None
        max_freq = None

    return {
        "physical_cores": psutil.cpu_count(logical=False),
        "logical_cores": psutil.cpu_count(logical=True),
        "current_frequency": current_freq,
        "max_frequency": max_freq,
        "usage_percent": psutil.cpu_percent(interval=1),
    }


def get_memory_info() -> dict[str, int | float]:
    """
    Get system memory information.

    Returns:
        Dictionary containing memory details in bytes (and percent as float)

    Example:
        >>> info = get_memory_info()
        >>> gb = 1024**3
        >>> print(f"RAM: {info['available'] / gb:.1f} GB / {info['total'] / gb:.1f} GB")
    """
    mem = psutil.virtual_memory()
    return {
        "total": mem.total,
        "available": mem.available,
        "used": mem.used,
        "free": mem.free,
        "percent_used": mem.percent,
    }


def check_memory_available(required_gb: float) -> bool:
    """
    Check if sufficient memory is available.

    Args:
        required_gb: Required memory in gigabytes

    Returns:
        True if sufficient memory available, False otherwise

    Example:
        >>> if not check_memory_available(8.0):
        ...     print("Insufficient memory! Need at least 8 GB")
    """
    mem_info = get_memory_info()
    available_gb = mem_info["available"] / (1024**3)
    return available_gb >= required_gb


def get_disk_usage(path: str = ".") -> dict[str, int | float]:
    """
    Get disk usage information for a path.

    Args:
        path: Path to check disk usage for

    Returns:
        Dictionary containing disk usage details in bytes (and percent as float)

    Example:
        >>> usage = get_disk_usage("/data")
        >>> gb = 1024**3
        >>> print(f"Disk: {usage['free'] / gb:.1f} GB free")
    """
    usage = psutil.disk_usage(path)
    return {
        "total": usage.total,
        "used": usage.used,
        "free": usage.free,
        "percent_used": usage.percent,
    }


def get_pytorch_info() -> dict[str, Any]:
    """
    Get PyTorch installation and configuration information.

    Returns:
        Dictionary containing PyTorch details

    Example:
        >>> info = get_pytorch_info()
        >>> print(f"PyTorch version: {info['version']}")
        >>> print(f"CUDA available: {info['cuda_available']}")
    """
    cuda_version = None
    if torch.cuda.is_available() and hasattr(torch, "version"):
        cuda_version = torch.version.cuda  # type: ignore

    return {
        "version": torch.__version__,
        "cuda_available": torch.cuda.is_available(),
        "cuda_version": cuda_version,
        "cudnn_version": torch.backends.cudnn.version() if torch.cuda.is_available() else None,
        "mps_available": hasattr(torch.backends, "mps") and torch.backends.mps.is_available(),
        "num_gpus": get_device_count(),
        "device_names": [get_device_name(i) for i in range(get_device_count())],
    }


def print_system_info():
    """
    Print comprehensive system information to console.

    Example:
        >>> print_system_info()
        ========== System Information ==========
        OS: Darwin 23.1.0
        Architecture: arm64 (64bit)
        ...
    """
    platform_info = get_platform_info()
    cpu_info = get_cpu_info()
    memory_info = get_memory_info()
    pytorch_info = get_pytorch_info()

    gb = 1024**3

    print("=" * 50)
    print("System Information")
    print("=" * 50)

    print("\n[Platform]")
    print(f"OS: {platform_info['system']} {platform_info['release']}")
    print(f"Architecture: {platform_info['machine']} ({platform_info['architecture']})")
    print(f"Processor: {platform_info['processor']}")
    print(f"Python: {platform_info['python_version']} ({platform_info['python_implementation']})")
    print(f"Apple Silicon: {is_apple_silicon()}")

    print("\n[CPU]")
    print(f"Physical Cores: {cpu_info['physical_cores']}")
    print(f"Logical Cores: {cpu_info['logical_cores']}")
    if cpu_info["current_frequency"]:
        print(f"Frequency: {cpu_info['current_frequency']:.0f} MHz")
    print(f"Usage: {cpu_info['usage_percent']:.1f}%")

    print("\n[Memory]")
    print(f"Total: {memory_info['total'] / gb:.2f} GB")
    print(f"Available: {memory_info['available'] / gb:.2f} GB")
    print(f"Used: {memory_info['used'] / gb:.2f} GB ({memory_info['percent_used']:.1f}%)")

    print("\n[PyTorch]")
    print(f"Version: {pytorch_info['version']}")
    print(f"CUDA Available: {pytorch_info['cuda_available']}")
    if pytorch_info["cuda_available"]:
        print(f"CUDA Version: {pytorch_info['cuda_version']}")
        print(f"cuDNN Version: {pytorch_info['cudnn_version']}")
        print(f"Number of GPUs: {pytorch_info['num_gpus']}")
        for i, name in enumerate(pytorch_info["device_names"]):
            total, free = get_device_memory(i)
            print(f"  GPU {i}: {name}")
            print(f"    Memory: {free / gb:.2f} GB / {total / gb:.2f} GB")
    print(f"MPS Available: {pytorch_info['mps_available']}")

    print("\n[Recommended Device]")
    device = get_device()
    print(f"Device: {device}")

    print("=" * 50)


def set_num_threads(num_threads: int | None = None):
    """
    Set the number of threads for PyTorch operations.

    Args:
        num_threads: Number of threads to use. If None, uses CPU count.

    Example:
        >>> set_num_threads(4)  # Use 4 threads
        >>> set_num_threads(None)  # Use all available threads
    """
    if num_threads is None:
        num_threads = psutil.cpu_count(logical=True)

    # Ensure num_threads is not None before passing to torch
    if num_threads is not None:
        torch.set_num_threads(num_threads)
        torch.set_num_interop_threads(num_threads)


def optimize_for_device(device: str | None = None) -> str:
    """
    Optimize PyTorch settings for the target device.

    Args:
        device: Target device ("cpu", "cuda", "mps", or None for auto-detect)

    Returns:
        Selected device string

    Example:
        >>> device = optimize_for_device()
        >>> print(f"Optimized for: {device}")
    """
    if device is None:
        device = get_device()

    if device == "cuda":
        # Enable cuDNN autotuner for better performance
        torch.backends.cudnn.benchmark = True
        # Enable TF32 on Ampere GPUs for faster matmul
        torch.backends.cuda.matmul.allow_tf32 = True
        torch.backends.cudnn.allow_tf32 = True

    elif device == "cpu":
        # Optimize CPU performance
        if is_apple_silicon():
            # Apple Silicon optimizations
            set_num_threads(psutil.cpu_count(logical=False))  # Use physical cores only
        else:
            # x86 optimizations
            set_num_threads(None)  # Use all threads

    elif device == "mps":
        # MPS (Apple Silicon GPU) optimizations
        # Currently limited optimizations available
        pass

    return device


def check_system_requirements(
    min_memory_gb: float = 4.0, min_disk_gb: float = 10.0, require_gpu: bool = False
) -> tuple[bool, str]:
    """
    Check if system meets minimum requirements.

    Args:
        min_memory_gb: Minimum required RAM in GB
        min_disk_gb: Minimum required disk space in GB
        require_gpu: Whether GPU is required

    Returns:
        Tuple of (meets_requirements, error_message)

    Example:
        >>> meets_req, msg = check_system_requirements(min_memory_gb=8.0)
        >>> if not meets_req:
        ...     print(f"System requirements not met: {msg}")
    """
    gb = 1024**3

    # Check memory
    mem_info = get_memory_info()
    available_memory_gb = mem_info["available"] / gb
    if available_memory_gb < min_memory_gb:
        return False, f"Insufficient memory: {available_memory_gb:.1f} GB available, {min_memory_gb:.1f} GB required"

    # Check disk space
    disk_info = get_disk_usage()
    free_disk_gb = disk_info["free"] / gb
    if free_disk_gb < min_disk_gb:
        return False, f"Insufficient disk space: {free_disk_gb:.1f} GB free, {min_disk_gb:.1f} GB required"

    # Check GPU if required
    if require_gpu:
        if not torch.cuda.is_available():
            return False, "GPU required but CUDA not available"

        # Check GPU memory
        total_gpu_mem, free_gpu_mem = get_device_memory(0)
        if total_gpu_mem == 0:
            return False, "GPU required but no GPU detected"

    return True, "All system requirements met"


# Environment variable helpers
def get_env_bool(var_name: str, default: bool = False) -> bool:
    """Get boolean value from environment variable."""
    value = os.environ.get(var_name, str(default)).lower()
    return value in ("true", "1", "yes", "on")


def get_env_int(var_name: str, default: int = 0) -> int:
    """Get integer value from environment variable."""
    try:
        return int(os.environ.get(var_name, default))
    except (ValueError, TypeError):
        return default


def get_env_float(var_name: str, default: float = 0.0) -> float:
    """Get float value from environment variable."""
    try:
        return float(os.environ.get(var_name, default))
    except (ValueError, TypeError):
        return default
