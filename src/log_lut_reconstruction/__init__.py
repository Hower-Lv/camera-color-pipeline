"""Reconstruct camera Log responses and deploy chart-validated LUTs."""

from .config import PipelineConfig, QualityThresholds
from .log_templates import (
    PUBLIC_LOG_TEMPLATES,
    PublicLogFit,
    PublicLogTemplate,
    compare_public_log_templates,
    encode_public_log,
    fit_public_log_template,
)
from .lut_gallery import run_lut_gallery
from .measurement_policy import (
    MeasurementKind,
    MeasurementPolicyConfig,
    MeasurementPolicyResult,
    SpatialCorrectionSpec,
    apply_selective_measurement_policy,
    apply_spatial_correction_before_lut,
)
from .quality import evaluate_quality_gates


def run_synthetic_pipeline(*args, **kwargs):
    """Run the integrated example after the three component packages are installed."""
    from .orchestrator import run_synthetic_pipeline as _run_synthetic_pipeline

    return _run_synthetic_pipeline(*args, **kwargs)

__all__ = [
    "PipelineConfig",
    "PUBLIC_LOG_TEMPLATES",
    "PublicLogFit",
    "PublicLogTemplate",
    "QualityThresholds",
    "compare_public_log_templates",
    "encode_public_log",
    "evaluate_quality_gates",
    "fit_public_log_template",
    "run_synthetic_pipeline",
    "run_lut_gallery",
    "MeasurementKind",
    "MeasurementPolicyConfig",
    "MeasurementPolicyResult",
    "SpatialCorrectionSpec",
    "apply_selective_measurement_policy",
    "apply_spatial_correction_before_lut",
]

__version__ = "0.1.0"
