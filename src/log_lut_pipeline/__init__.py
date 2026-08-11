"""Reconstruct camera Log responses and deploy chart-validated LUTs."""

from .config import PipelineConfig, QualityThresholds
from .quality import evaluate_quality_gates


def run_synthetic_pipeline(*args, **kwargs):
    """Run the integrated example after the three component packages are installed."""
    from .orchestrator import run_synthetic_pipeline as _run_synthetic_pipeline

    return _run_synthetic_pipeline(*args, **kwargs)

__all__ = [
    "PipelineConfig",
    "QualityThresholds",
    "evaluate_quality_gates",
    "run_synthetic_pipeline",
]

__version__ = "0.1.0"
