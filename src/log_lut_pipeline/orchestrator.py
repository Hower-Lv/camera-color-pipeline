from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np

from .config import PipelineConfig
from .provenance import write_provenance_manifest
from .quality import evaluate_quality_gates

try:
    from chart_lut_builder import D65_WHITE, ToneCurve, build_model, leave_one_capture_out
    from log_reconstruction import (
        LogTemplate,
        fit_hlg_log_pair,
        fit_raw_hlg_log,
        hlg_oetf,
    )
    from spectral_color_calibrator import (
        apply_ccm,
        apply_flat_field,
        delta_e_2000,
        fit_ccm,
        fit_white_field,
        reflectance_to_xyz,
        summarize_delta_e,
        xyz_to_lab,
    )
except ImportError as exc:
    raise RuntimeError(
        "Install the three component projects before running the integrated pipeline"
    ) from exc


def _pseudo_cmfs(wavelengths: np.ndarray) -> np.ndarray:
    red = np.exp(-0.5 * ((wavelengths - 600.0) / 42.0) ** 2)
    green = np.exp(-0.5 * ((wavelengths - 545.0) / 34.0) ** 2)
    blue = np.exp(-0.5 * ((wavelengths - 450.0) / 28.0) ** 2)
    return np.column_stack([red, green, blue])


def _synthetic_reflectances(
    wavelengths: np.ndarray, patch_count: int, rng: np.random.Generator
) -> np.ndarray:
    reflectances = []
    gray_count = min(6, patch_count)
    for level in np.linspace(0.04, 0.92, gray_count):
        reflectances.append(np.full(wavelengths.shape, level))
    centers = np.array([430.0, 485.0, 540.0, 595.0, 650.0])
    basis = np.stack(
        [np.exp(-0.5 * ((wavelengths - center) / 30.0) ** 2) for center in centers]
    )
    while len(reflectances) < patch_count:
        weights = rng.uniform(0.0, 1.0, size=centers.size)
        spectrum = 0.025 + weights @ basis
        spectrum /= np.max(spectrum)
        spectrum *= rng.uniform(0.35, 0.95)
        reflectances.append(np.clip(spectrum, 0.02, 0.95))
    return np.asarray(reflectances)


def _log_encode(values: np.ndarray, curvature: float) -> np.ndarray:
    return np.log2(1.0 + curvature * np.maximum(values, 0.0)) / np.log2(1.0 + curvature)


def _limited_code(normalized: np.ndarray) -> np.ndarray:
    return 64.0 + 876.0 * np.asarray(normalized, dtype=np.float64)


def _write_csv(path: Path, header: list[str], rows: np.ndarray) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows.tolist())


def run_synthetic_pipeline(
    config: PipelineConfig,
    output_dir: str | Path,
    *,
    config_path: str | Path | None = None,
) -> dict[str, object]:
    config.validate()
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(config.seed)

    wavelengths = np.arange(400.0, 701.0, 10.0)
    cmfs = _pseudo_cmfs(wavelengths)
    illuminant = 0.78 + 0.22 * (wavelengths - wavelengths.min()) / np.ptp(wavelengths)
    reflectances = _synthetic_reflectances(wavelengths, config.patch_count, rng)
    target_xyz = reflectance_to_xyz(wavelengths, reflectances, illuminant, cmfs)
    source_white = reflectance_to_xyz(wavelengths, np.ones((1, wavelengths.size)), illuminant, cmfs)[0]

    sensor_mix = np.array(
        [[0.74, 0.15, 0.05], [0.12, 0.78, 0.13], [0.04, 0.16, 0.82]],
        dtype=np.float64,
    )
    camera_rgb = target_xyz @ sensor_mix
    camera_white = source_white @ sensor_mix
    camera_rgb /= camera_white

    height, width = 64, 96
    yy, xx = np.mgrid[-1.0:1.0:complex(height), -1.0:1.0:complex(width)]
    field = np.stack(
        [
            np.exp(0.08 * yy + 0.025 * xx + 0.018 * yy**2),
            np.exp(0.065 * yy - 0.012 * xx + 0.012 * xx * yy),
            np.exp(0.095 * yy + 0.018 * xx + 0.021 * xx**2),
        ],
        axis=-1,
    )
    white_image = field * camera_white[None, None, :]
    flat_model = fit_white_field(white_image, stride=4)
    corrected_white = apply_flat_field(white_image, flat_model)
    normalized_white = corrected_white / np.median(corrected_white, axis=(0, 1), keepdims=True)
    flat_field_residual_cv = float(np.max(np.std(normalized_white, axis=(0, 1))))

    ccm = fit_ccm(camera_rgb, target_xyz, model=config.color_model, ridge=config.ridge)
    ccm_prediction = np.clip(apply_ccm(camera_rgb, ccm), 0.0, None)
    ccm_delta = delta_e_2000(
        xyz_to_lab(ccm_prediction, source_white), xyz_to_lab(target_xyz, source_white)
    )
    ccm_summary = summarize_delta_e(ccm_delta)

    frontend = np.array(
        [[0.94, 0.035, 0.010], [0.018, 0.955, 0.012], [0.012, 0.045, 0.925]],
        dtype=np.float64,
    )
    raw_pair = rng.beta(1.2, 3.0, size=(config.pair_sample_count, 3))
    common_pair = np.clip(raw_pair @ frontend.T, 0.0, 1.0)
    common_luma = common_pair @ np.array([0.2627, 0.6780, 0.0593])
    hlg_rgb = hlg_oetf(common_pair)
    hlg_luma_code = _limited_code(hlg_oetf(common_luma))
    log_luma_code = _limited_code(_log_encode(common_luma, config.log_curvature))
    template = LogTemplate(curvature=config.log_curvature)
    method_a = fit_hlg_log_pair(hlg_luma_code, log_luma_code, template=template)
    method_b = fit_raw_hlg_log(raw_pair, hlg_rgb, log_luma_code, template=template)

    linear_knots = np.linspace(0.0, 1.0, 513)
    encoded_a = method_a.log_fit.predict(linear_knots)
    encoded_b = method_b.log_fit.predict(linear_knots)
    consensus_encoded = np.maximum.accumulate((encoded_a + encoded_b) / 2.0)
    tone_consensus_rmse = float(np.sqrt(np.mean((encoded_a - encoded_b) ** 2)))
    tone_curve = ToneCurve.from_samples(consensus_encoded, linear_knots)

    common_chart = np.clip(camera_rgb @ frontend.T, 0.0, 1.0)
    encoded_chart = _log_encode(common_chart, config.log_curvature)
    encoded_rows = []
    xyz_rows = []
    capture_ids = []
    for capture_index in range(config.capture_count):
        noise = rng.normal(0.0, 0.0002, size=encoded_chart.shape)
        encoded_rows.append(np.clip(encoded_chart + noise, 0.0, 1.0))
        xyz_rows.append(target_xyz)
        capture_ids.extend([f"capture_{capture_index + 1}"] * config.patch_count)
    encoded_rows_array = np.vstack(encoded_rows)
    xyz_rows_array = np.vstack(xyz_rows)

    cross_capture = leave_one_capture_out(
        encoded_rows_array,
        xyz_rows_array,
        capture_ids,
        tone_curve,
        color_model=config.color_model,
        ridge=config.ridge,
        source_white=source_white,
        destination_white=D65_WHITE,
        lut_size=config.lut_size,
        neutral_width_cells=config.neutral_width_cells,
    )
    model = build_model(
        encoded_rows_array,
        xyz_rows_array,
        tone_curve,
        color_model=config.color_model,
        ridge=config.ridge,
        source_white=source_white,
        destination_white=D65_WHITE,
        lut_size=config.lut_size,
        neutral_width_cells=config.neutral_width_cells,
    )
    cube_path = output / "synthetic_camera_log_to_srgb.cube"
    model.write_cube(str(cube_path))
    validation = model.validate_cube(str(cube_path), encoded_rows_array, xyz_rows_array)

    gray_axis = validation["gray_axis"]
    metrics = {
        "flat_field_residual_cv": flat_field_residual_cv,
        "ccm_mean_delta_e00": ccm_summary["mean"],
        "method_a_rmse": method_a.log_fit.rmse,
        "method_b_rmse": method_b.log_fit.rmse,
        "tone_consensus_rmse": tone_consensus_rmse,
        "lut_mean_delta_e00": validation["mean_delta_e00"],
        "lut_p95_delta_e00": validation["p95_delta_e00"],
        "gray_reverse_steps": gray_axis["reverse_steps"],
        "gray_channel_spread": gray_axis["maximum_channel_spread"],
    }
    quality = evaluate_quality_gates(metrics, config.quality)

    target_path = output / "synthetic_target_xyz.csv"
    tone_path = output / "synthetic_tone_consensus.csv"
    _write_csv(target_path, ["X", "Y", "Z"], target_xyz)
    _write_csv(
        tone_path,
        ["linear", "method_a_encoded", "method_b_encoded", "consensus_encoded"],
        np.column_stack([linear_knots, encoded_a, encoded_b, consensus_encoded]),
    )

    report = {
        "pipeline": "log-lut-pipeline",
        "status": quality["status"],
        "stages": {
            "spectral_targets": {
                "patch_count": config.patch_count,
                "source_white_xyz": source_white.tolist(),
            },
            "spatial_correction": {"flat_field_residual_cv": flat_field_residual_cv},
            "static_color_calibration": {
                "model": config.color_model,
                "delta_e00": ccm_summary,
            },
            "paired_log_reconstruction": {
                "method_a_rmse": method_a.log_fit.rmse,
                "method_b_rmse": method_b.log_fit.rmse,
                "tone_consensus_rmse": tone_consensus_rmse,
                "method_a_input_range": [method_a.hlg_linear_min, method_a.hlg_linear_max],
                "method_b_input_range": [method_b.common_linear_min, method_b.common_linear_max],
            },
            "lut_deployment": {
                "lut_size": config.lut_size,
                "mean_delta_e00": validation["mean_delta_e00"],
                "p95_delta_e00": validation["p95_delta_e00"],
                "max_delta_e00": validation["max_delta_e00"],
                "gray_axis": gray_axis,
            },
            "cross_capture_validation": cross_capture,
        },
        "quality_gates": quality,
    }
    report_path = output / "pipeline_report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    provenance_inputs = [config_path] if config_path is not None else []
    manifest_path = output / "provenance.json"
    write_provenance_manifest(
        manifest_path,
        root=Path(config_path).resolve().parent.parent if config_path is not None else output,
        inputs=provenance_inputs,
        artifacts=[cube_path, target_path, tone_path, report_path],
        metadata={
            "pipeline": "log-lut-pipeline",
            "seed": config.seed,
            "status": quality["status"],
        },
    )
    return report
