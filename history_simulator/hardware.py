"""Best-effort detection of how much memory is available to run a local
model against, so config.py can size CHAT_MODEL to the machine it's running
on (Apple Silicon's unified memory, or an NVIDIA GPU's VRAM) instead of a
single hardcoded model that's wrong on every machine but one.
"""

import platform
import subprocess


def available_memory_gb() -> float:
    """Total unified memory on Apple Silicon, or the first NVIDIA GPU's
    total VRAM everywhere else. Returns 0.0 if neither can be detected,
    which config.py treats as "assume the smallest supported machine"."""
    if platform.system() == "Darwin":
        return _apple_unified_memory_gb()
    return _nvidia_vram_gb()


def _apple_unified_memory_gb() -> float:
    try:
        out = subprocess.run(
            ["sysctl", "-n", "hw.memsize"],
            capture_output=True, text=True, timeout=5, check=True,
        )
        return int(out.stdout.strip()) / (1024 ** 3)
    except (subprocess.SubprocessError, ValueError, FileNotFoundError):
        return 0.0


def _nvidia_vram_gb() -> float:
    """VRAM of the first GPU reported by nvidia-smi. Multi-GPU boxes are
    treated as having just that much memory, since Ollama doesn't split a
    single model's weights across devices by default."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5, check=True,
        )
        first_gpu_mib = int(out.stdout.strip().splitlines()[0])
        return first_gpu_mib / 1024
    except (subprocess.SubprocessError, ValueError, FileNotFoundError, IndexError):
        return 0.0
