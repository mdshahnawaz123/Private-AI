"""
Observability for Expo Design AI (Phase 9).

Tracks:
- Request latency
- Document processing time
- OCR time
- Retrieval time
- LLM inference time
- GPU utilization
- CPU utilization
- Memory
- Queue length
- Failed jobs
- Model errors
- Agent failures
- Database performance

Provides health endpoints and metrics.
"""
import os
import time
import psutil
import datetime
from typing import Dict, Any, Optional
from dataclasses import dataclass, field

try:
    from loguru import logger
except Exception:
    class _Nop:
        def __getattr__(self, _): return lambda *a, **k: None
    logger = _Nop()


@dataclass
class MetricRecord:
    """A single metric record."""
    name: str
    value: float
    unit: str
    timestamp: str
    labels: Dict[str, str] = field(default_factory=dict)


class Observability:
    """
    Metrics collection and health monitoring.
    """

    def __init__(self):
        self._metrics: list = []
        self._start_time = time.time()

    def record(self, name: str, value: float, unit: str = "",
               labels: Dict[str, str] = None):
        """Record a metric."""
        self._metrics.append(MetricRecord(
            name=name,
            value=value,
            unit=unit,
            timestamp=datetime.datetime.utcnow().isoformat(),
            labels=labels or {},
        ))

    def time_operation(self, name: str):
        """Context manager for timing an operation."""
        return _Timer(self, name)

    def get_system_metrics(self) -> Dict[str, Any]:
        """Get current system metrics."""
        metrics = {
            "cpu_percent": psutil.cpu_percent(interval=0.1),
            "memory_percent": psutil.virtual_memory().percent,
            "memory_used_gb": psutil.virtual_memory().used / (1024 ** 3),
            "memory_total_gb": psutil.virtual_memory().total / (1024 ** 3),
            "disk_percent": psutil.disk_usage('/').percent,
            "uptime_seconds": time.time() - self._start_time,
        }

        # GPU metrics (if available)
        try:
            import subprocess
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                lines = result.stdout.strip().split("\n")
                for i, line in enumerate(lines):
                    parts = line.split(",")
                    if len(parts) >= 3:
                        metrics[f"gpu_{i}_utilization"] = float(parts[0].strip())
                        metrics[f"gpu_{i}_memory_used_mb"] = float(parts[1].strip())
                        metrics[f"gpu_{i}_memory_total_mb"] = float(parts[2].strip())
        except Exception:
            pass

        return metrics

    def get_metrics_summary(self) -> Dict[str, Any]:
        """Get summary of all recorded metrics."""
        if not self._metrics:
            return {"message": "No metrics recorded"}

        # Group by name
        by_name = {}
        for m in self._metrics:
            if m.name not in by_name:
                by_name[m.name] = []
            by_name[m.name].append(m.value)

        summary = {}
        for name, values in by_name.items():
            summary[name] = {
                "count": len(values),
                "min": min(values),
                "max": max(values),
                "avg": sum(values) / len(values),
                "last": values[-1],
            }

        return summary

    def health_check(self) -> Dict[str, Any]:
        """Comprehensive health check."""
        health = {
            "status": "healthy",
            "timestamp": datetime.datetime.utcnow().isoformat(),
            "uptime_seconds": time.time() - self._start_time,
            "system": self.get_system_metrics(),
            "services": {},
        }

        # Check database
        try:
            import db
            with db.SessionLocal() as s:
                s.execute("SELECT 1")
            health["services"]["database"] = "healthy"
        except Exception as e:
            health["services"]["database"] = f"unhealthy: {e}"
            health["status"] = "degraded"

        # Check Ollama
        try:
            import httpx
            r = httpx.get(os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434") + "/api/tags", timeout=5)
            if r.status_code == 200:
                health["services"]["ollama"] = "healthy"
            else:
                health["services"]["ollama"] = f"degraded: HTTP {r.status_code}"
                health["status"] = "degraded"
        except Exception as e:
            health["services"]["ollama"] = f"unhealthy: {e}"
            health["status"] = "degraded"

        # Check Redis (if configured)
        if os.getenv("CELERY_BROKER_URL"):
            try:
                import redis
                r = redis.from_url(os.getenv("CELERY_BROKER_URL"))
                r.ping()
                health["services"]["redis"] = "healthy"
            except Exception as e:
                health["services"]["redis"] = f"unhealthy: {e}"

        return health


class _Timer:
    """Context manager for timing operations."""

    def __init__(self, observability: Observability, name: str):
        self._obs = observability
        self._name = name
        self._start = 0

    def __enter__(self):
        self._start = time.time()
        return self

    def __exit__(self, *args):
        elapsed = (time.time() - self._start) * 1000
        self._obs.record(self._name, elapsed, "ms")


# Singleton instance
_observability = Observability()


def get_observability() -> Observability:
    """Get the global observability instance."""
    return _observability
