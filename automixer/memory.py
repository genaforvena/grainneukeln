"""Memory monitoring and optimization utilities for grainneukeln.

The grinder routinely pushes 200-300 MB on long sources (source audio + librosa arrays +
mix chunks + final concat). On memory-constrained nodes (mesh-home with 32 GB shared across
12 opencode instances + ollama + voice-clone), this tips the system into OOM. These utilities
let the operator monitor memory and enable low-memory modes.
"""
import gc
import os


def get_memory_mb():
    """Return current process RSS in MB. Returns 0 if psutil unavailable."""
    try:
        import psutil
        return psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024
    except ImportError:
        return 0


def log_memory(label, threshold_mb=150):
    """Print current memory if above threshold. Use at key phases to track bloat."""
    mb = get_memory_mb()
    if mb > threshold_mb:
        print(f"[memory] {label}: {mb:.0f} MB")


def force_gc():
    """Force garbage collection and return freed MB (approx)."""
    before = get_memory_mb()
    gc.collect()
    after = get_memory_mb()
    return max(0, before - after)


def check_memory_pressure(warn_mb=500, critical_mb=1000):
    """Check if system is under memory pressure. Returns 'ok', 'warn', or 'critical'."""
    mb = get_memory_mb()
    if mb > critical_mb:
        return "critical"
    elif mb > warn_mb:
        return "warn"
    return "ok"
