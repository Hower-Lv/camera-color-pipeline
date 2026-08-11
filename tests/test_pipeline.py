from __future__ import annotations

from dataclasses import replace

from log_lut_reconstruction import PipelineConfig, QualityThresholds
from log_lut_reconstruction.orchestrator import run_synthetic_pipeline
from log_lut_reconstruction.quality import evaluate_quality_gates


def test_synthetic_pipeline_runs_end_to_end(tmp_path) -> None:
    config = PipelineConfig(
        seed=12,
        patch_count=18,
        pair_sample_count=512,
        capture_count=2,
        lut_size=9,
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
