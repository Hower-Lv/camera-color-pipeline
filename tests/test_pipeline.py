from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from log_lut_reconstruction import PipelineConfig, QualityThresholds
from log_lut_reconstruction.log_templates import (
    PUBLIC_LOG_TEMPLATES,
    compare_public_log_templates,
    encode_public_log,
    fit_public_log_template,
)
from log_lut_reconstruction.measurement_policy import (
    MeasurementKind,
    SpatialCorrectionSpec,
    apply_selective_measurement_policy,
    apply_spatial_correction_before_lut,
)
from log_lut_reconstruction.quality import evaluate_quality_gates


def test_synthetic_pipeline_runs_end_to_end(tmp_path) -> None:
    try:
        from log_lut_reconstruction.orchestrator import run_synthetic_pipeline
    except RuntimeError as exc:
        pytest.skip(str(exc))
    config = PipelineConfig(
        seed=12,
        patch_count=18,
        pair_sample_count=512,
        capture_count=2,
        lut_size=65,
        neutral_width_cells=1,
    )
    report = run_synthetic_pipeline(config, tmp_path)
    assert report["status"] == "pass"
    assert (tmp_path / "synthetic_camera_log_to_srgb.cube").is_file()
    assert (tmp_path / "pipeline_report.json").is_file()
    assert (tmp_path / "provenance.json").is_file()
    assert set(report["stages"]) == {
        "spectral_targets",
        "spatial_correction",
        "measurement_point_policy",
        "static_color_calibration",
        "paired_log_reconstruction",
        "lut_deployment",
        "cross_capture_validation",
    }


def test_quality_gate_reports_failure() -> None:
    thresholds = replace(QualityThresholds(), max_lut_mean_delta_e00=0.01)
    metrics = {
        "flat_field_residual_cv": 0.0,
        "ccm_mean_delta_e00": 0.0,
        "method_a_rmse": 0.0,
        "method_b_rmse": 0.0,
        "tone_consensus_rmse": 0.0,
        "lut_mean_delta_e00": 0.5,
        "lut_p95_delta_e00": 0.5,
        "gray_reverse_steps": 0,
        "gray_channel_spread": 0.0,
    }
    result = evaluate_quality_gates(metrics, thresholds)
    assert result["status"] == "fail"


def test_public_log_registry_contains_documented_templates() -> None:
    assert set(PUBLIC_LOG_TEMPLATES) == {
        "dji_d_log",
        "insta360_i_log",
        "oppo_o_log2",
        "arri_logc4",
        "sony_s_log3",
        "panasonic_v_log",
    }
    assert all(template.reference for template in PUBLIC_LOG_TEMPLATES.values())
    linear = np.geomspace(1e-6, 1.0, 256)
    for key in PUBLIC_LOG_TEMPLATES:
        encoded = encode_public_log(key, linear)
        assert np.all(np.isfinite(encoded))
        assert np.all(np.diff(encoded) > 0.0)


def test_public_log_fit_recovers_scaled_template() -> None:
    linear = np.geomspace(1e-4, 1.0, 180)
    black = encode_public_log("dji_d_log", np.asarray([0.0]))[0]
    encoded = 0.83 * (encode_public_log("dji_d_log", 1.7 * linear) - black)
    fit = fit_public_log_template(linear, encoded, "dji_d_log")
    assert fit.rmse < 1e-6
    assert abs(fit.input_scale - 1.7) < 2e-3
    assert abs(fit.output_gain - 0.83) < 2e-3


def test_public_log_comparison_reports_group_validation_and_equivalence() -> None:
    linear = np.geomspace(1e-4, 1.0, 120)
    black = encode_public_log("oppo_o_log2", np.asarray([0.0]))[0]
    encoded = 0.92 * (encode_public_log("oppo_o_log2", 1.25 * linear) - black)
    groups = [f"capture_{index // 30}" for index in range(linear.size)]
    result = compare_public_log_templates(
        linear,
        encoded,
        template_keys=["oppo_o_log2", "arri_logc4", "sony_s_log3"],
        group_ids=groups,
    )
    assert result["ranking_metric"] == "leave_group_out_rmse"
    assert result["fits"][0]["leave_group_out_rmse"] is not None
    assert len(result["pairwise_curve_differences"]) == 3


def test_selective_policy_only_corrects_controlled_exposure_x() -> None:
    linear = np.asarray([0.0, 0.25, 0.42, 0.65])
    encoded = np.asarray([64.0, 240.0, 410.0, 620.0])
    kinds = [
        MeasurementKind.BLACK_ANCHOR,
        MeasurementKind.CONTROLLED_EXPOSURE,
        MeasurementKind.LOCAL_WHITE_GRADIENT,
        MeasurementKind.PAIRED_TRANSFER,
    ]
    result = apply_selective_measurement_policy(
        linear,
        encoded,
        kinds,
        spatial_factors=np.asarray([1.0, 0.8, 1.0, 1.0]),
    )
    assert np.allclose(result.linear, [0.0, 0.2, 0.42, 0.65])
    assert np.array_equal(result.encoded, encoded)
    summary = {row["kind"]: row for row in result.summary()["groups"]}
    assert summary["controlled_exposure"]["action"] == "multiply_linear_x_only"
    assert summary["local_white_gradient"]["encoded_values_modified"] is False


def test_selective_policy_rejects_spatial_factor_on_same_position_pair() -> None:
    with pytest.raises(ValueError, match="only valid for controlled_exposure"):
        apply_selective_measurement_policy(
            np.asarray([0.2]),
            np.asarray([0.4]),
            [MeasurementKind.PAIRED_TRANSFER],
            spatial_factors=np.asarray([0.9]),
        )


def test_spatial_correction_rejects_geometry_mismatch_before_lut() -> None:
    spec = SpatialCorrectionSpec("geometry_a")
    with pytest.raises(ValueError, match="geometry mismatch"):
        apply_spatial_correction_before_lut(
            np.ones((4, 4, 3)),
            object(),
            spec,
            actual_geometry_id="geometry_b",
        )
