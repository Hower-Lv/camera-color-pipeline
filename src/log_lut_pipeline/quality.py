from __future__ import annotations

from dataclasses import asdict

from .config import QualityThresholds


def evaluate_quality_gates(
    metrics: dict[str, float | int], thresholds: QualityThresholds
) -> dict[str, object]:
    limits = asdict(thresholds)
    metric_names = {
        "max_flat_field_residual_cv": "flat_field_residual_cv",
        "max_ccm_mean_delta_e00": "ccm_mean_delta_e00",
        "max_method_a_rmse": "method_a_rmse",
        "max_method_b_rmse": "method_b_rmse",
        "max_tone_consensus_rmse": "tone_consensus_rmse",
        "max_lut_mean_delta_e00": "lut_mean_delta_e00",
        "max_lut_p95_delta_e00": "lut_p95_delta_e00",
        "max_gray_reverse_steps": "gray_reverse_steps",
        "max_gray_channel_spread": "gray_channel_spread",
    }
    checks = []
    for threshold_name, metric_name in metric_names.items():
        value = metrics[metric_name]
        limit = limits[threshold_name]
        checks.append(
            {
                "metric": metric_name,
                "value": value,
                "operator": "<=",
                "limit": limit,
                "passed": bool(value <= limit),
            }
        )
    return {
        "status": "pass" if all(check["passed"] for check in checks) else "fail",
        "checks": checks,
    }
