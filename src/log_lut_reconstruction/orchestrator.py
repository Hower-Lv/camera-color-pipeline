from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np

from .color_adaptation import cat16_adaptation
from .config import PipelineConfig
from .integration import reconstruct_dual_path
from .measurement_policy import (
    MeasurementKind,
    MeasurementPolicyResult,
    SpatialCorrectionSpec,
    apply_selective_measurement_policy,
    apply_spatial_correction_before_lut,
)
from .provenance import write_provenance_manifest
from .quality import evaluate_quality_gates

try:
    from chart_lut_builder import (
        D65_WHITE,
        XYZ_TO_SRGB,
        ToneCurve,
        build_model,
        leave_one_capture_out,
    )
    from log_reconstruction import LogTemplate, hlg_oetf
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
    result = np.asarray(reflectances)
    chromatic = result[gray_count:]
    neutral = np.mean(chromatic, axis=1, keepdims=True)
    result[gray_count:] = neutral + 0.6 * (chromatic - neutral)
    return result


def _log_encode(values: np.ndarray, curvature: float) -> np.ndarray:
    return np.log2(1.0 + curvature * np.maximum(values, 0.0)) / np.log2(1.0 + curvature)


def _limited_code(normalized: np.ndarray) -> np.ndarray:
    return 64.0 + 876.0 * np.asarray(normalized, dtype=np.float64)


def _write_csv(path: Path, header: list[str], rows: np.ndarray) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows.tolist())


def _write_measurement_policy_csv(
    path: Path,
    original_linear: np.ndarray,
    result: MeasurementPolicyResult,
) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "measurement_kind",
                "linear_before_policy",
                "spatial_factor",
                "linear_after_policy",
                "encoded_unchanged",
            ]
        )
        for kind, before, factor, after, encoded in zip(
            result.kinds,
            original_linear,
            result.spatial_factors,
            result.linear,
            result.encoded,
            strict=True,
        ):
            writer.writerow([kind, before, factor, after, encoded])


def _render_patch_grid(patches: np.ndarray, height: int, width: int) -> np.ndarray:
    values = np.asarray(patches, dtype=np.float64)
    columns = min(6, values.shape[0])
    rows = int(np.ceil(values.shape[0] / columns))
    image = np.zeros((height, width, 3), dtype=np.float64)
    row_edges = np.linspace(0, height, rows + 1, dtype=int)
    column_edges = np.linspace(0, width, columns + 1, dtype=int)
    for index, patch in enumerate(values):
        row, column = divmod(index, columns)
        image[
            row_edges[row] : row_edges[row + 1],
            column_edges[column] : column_edges[column + 1],
        ] = patch
    return image


def _sample_patch_grid(image: np.ndarray, patch_count: int) -> np.ndarray:
    values = np.asarray(image, dtype=np.float64)
    columns = min(6, patch_count)
    rows = int(np.ceil(patch_count / columns))
    row_edges = np.linspace(0, values.shape[0], rows + 1, dtype=int)
    column_edges = np.linspace(0, values.shape[1], columns + 1, dtype=int)
    samples = []
    for index in range(patch_count):
        row, column = divmod(index, columns)
        patch = values[
            row_edges[row] : row_edges[row + 1],
            column_edges[column] : column_edges[column + 1],
        ]
        samples.append(np.mean(patch, axis=(0, 1)))
    return np.asarray(samples)


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
    candidate_count = max(config.patch_count * 12, config.patch_count + 24)
    candidate_reflectances = _synthetic_reflectances(wavelengths, candidate_count, rng)
    candidate_xyz = reflectance_to_xyz(
        wavelengths, candidate_reflectances, illuminant, cmfs
    )
    source_white = reflectance_to_xyz(
        wavelengths, np.ones((1, wavelengths.size)), illuminant, cmfs
    )[0]
    adaptation = cat16_adaptation(source_white, D65_WHITE)
    candidate_xyz_d65 = candidate_xyz @ adaptation.T

    sensor_mix = np.array(
        [[0.74, 0.15, 0.05], [0.12, 0.78, 0.13], [0.04, 0.16, 0.82]],
        dtype=np.float64,
    )
    camera_white = source_white @ sensor_mix
    frontend = np.array(
        [[0.94, 0.035, 0.010], [0.018, 0.955, 0.012], [0.012, 0.045, 0.925]],
        dtype=np.float64,
    )
    frontend /= np.sum(frontend, axis=1, keepdims=True)
    candidate_camera_rgb = (candidate_xyz @ sensor_mix) / camera_white
    candidate_common_rgb = np.clip(candidate_camera_rgb @ frontend.T, 0.0, 1.0)
    candidate_destination_rgb = candidate_xyz_d65 @ XYZ_TO_SRGB.T
    gray_count = min(6, config.patch_count)
    neutral_width = config.neutral_width_cells / max(config.lut_size - 1, 1)
    encoded_candidate = _log_encode(candidate_common_rgb, config.log_curvature)
    chromatic = np.arange(gray_count, candidate_count)
    in_gamut = np.all(
        (candidate_destination_rgb[chromatic] >= 0.0)
        & (candidate_destination_rgb[chromatic] <= 1.0),
        axis=1,
    )
    outside_neutral_band = (
        np.ptp(encoded_candidate[chromatic], axis=1) > neutral_width + 0.01
    )
    selected_chromatic = chromatic[in_gamut & outside_neutral_band]
    needed_chromatic = config.patch_count - gray_count
    if selected_chromatic.size < needed_chromatic:
        raise RuntimeError("synthetic candidate pool cannot satisfy the LUT validation domain")
    selected = np.concatenate(
        [np.arange(gray_count), selected_chromatic[:needed_chromatic]]
    )
    target_xyz_source = candidate_xyz[selected]
    target_xyz_d65 = candidate_xyz_d65[selected]
    camera_rgb = candidate_camera_rgb[selected]

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
    spatial_spec = SpatialCorrectionSpec(config.measurement_policy.geometry_id)

    ccm = fit_ccm(camera_rgb, target_xyz_source, model=config.color_model, ridge=config.ridge)
    ccm_prediction = np.clip(apply_ccm(camera_rgb, ccm), 0.0, None)
    ccm_delta = delta_e_2000(
        xyz_to_lab(ccm_prediction, source_white),
        xyz_to_lab(target_xyz_source, source_white),
    )
    ccm_summary = summarize_delta_e(ccm_delta)

    raw_pair_rgb = rng.beta(1.2, 3.0, size=(config.pair_sample_count, 3))
    common_pair = np.clip(raw_pair_rgb @ frontend.T, 0.0, 1.0)
    common_luma = common_pair @ np.array([0.2627, 0.6780, 0.0593])
    hlg_luma_code = _limited_code(hlg_oetf(common_luma))
    log_luma_code = _limited_code(_log_encode(common_luma, config.log_curvature))
    raw_relative_linear = common_luma * rng.normal(
        1.0, 1e-6, size=config.pair_sample_count
    )
    controlled_linear = np.geomspace(0.004, 0.8, 9)
    controlled_factors = np.linspace(0.80, 0.94, controlled_linear.size)
    local_linear = np.geomspace(0.12, 0.18, 24)
    paired_linear = common_luma[:32]
    policy_linear = np.concatenate(
        [np.asarray([0.0]), controlled_linear, local_linear, paired_linear]
    )
    policy_factors = np.concatenate(
        [
            np.asarray([1.0]),
            controlled_factors,
            np.ones(local_linear.size + paired_linear.size),
        ]
    )
    policy_kinds = (
        [MeasurementKind.BLACK_ANCHOR]
        + [MeasurementKind.CONTROLLED_EXPOSURE] * controlled_linear.size
        + [MeasurementKind.LOCAL_WHITE_GRADIENT] * local_linear.size
        + [MeasurementKind.PAIRED_TRANSFER] * paired_linear.size
    )
    encoded_input_linear = policy_linear.copy()
    controlled_slice = slice(1, 1 + controlled_linear.size)
    encoded_input_linear[controlled_slice] *= controlled_factors
    policy_encoded = _limited_code(_log_encode(encoded_input_linear, config.log_curvature))
    measurement_policy = apply_selective_measurement_policy(
        policy_linear,
        policy_encoded,
        policy_kinds,
        spatial_factors=policy_factors,
    )
    template = LogTemplate(curvature=config.log_curvature)
    linear_knots = np.linspace(0.0, 1.0, 513)
    dual_path = reconstruct_dual_path(
        hlg_luma_code,
        raw_relative_linear,
        log_luma_code,
        template=template,
        linear_grid=linear_knots,
    )
    tone_curve = ToneCurve.from_samples(dual_path.consensus_encoded, dual_path.linear)

    common_chart = np.clip(camera_rgb @ frontend.T, 0.0, 1.0)
    chart_linear_image = _render_patch_grid(common_chart, height, width)
    observed_chart_image = chart_linear_image * field
    corrected_chart_image = apply_spatial_correction_before_lut(
        observed_chart_image,
        flat_model,
        spatial_spec,
        actual_geometry_id=config.measurement_policy.geometry_id,
    )
    corrected_chart_samples = _sample_patch_grid(corrected_chart_image, config.patch_count)
    encoded_chart = _log_encode(np.clip(corrected_chart_samples, 0.0, 1.0), config.log_curvature)
    encoded_rows = []
    xyz_rows = []
    capture_ids = []
    for capture_index in range(config.capture_count):
        noise = rng.normal(0.0, 0.0002, size=encoded_chart.shape)
        encoded_rows.append(np.clip(encoded_chart + noise, 0.0, 1.0))
        xyz_rows.append(target_xyz_d65)
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
        source_white=D65_WHITE,
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
        source_white=D65_WHITE,
        destination_white=D65_WHITE,
        lut_size=config.lut_size,
        neutral_width_cells=config.neutral_width_cells,
    )
    cube_path = output / "synthetic_camera_log_to_srgb.cube"
    model.write_cube(str(cube_path))
    in_memory_validation = model.evaluate(encoded_rows_array, xyz_rows_array)
    validation = model.validate_cube(str(cube_path), encoded_rows_array, xyz_rows_array)

    gray_axis = validation["gray_axis"]
    metrics = {
        "flat_field_residual_cv": flat_field_residual_cv,
        "ccm_mean_delta_e00": ccm_summary["mean"],
        "hlg_path_rmse": dual_path.hlg.log_fit.rmse,
        "raw_path_rmse": dual_path.raw.log_fit.rmse,
        "dual_path_disagreement_rmse": dual_path.disagreement_rmse,
        "lut_mean_delta_e00": validation["mean_delta_e00"],
        "lut_p95_delta_e00": validation["p95_delta_e00"],
        "gray_reverse_steps": gray_axis["reverse_luma_steps"],
        "gray_channel_spread": gray_axis["maximum_channel_spread"],
    }
    quality = evaluate_quality_gates(metrics, config.quality)

    target_path = output / "synthetic_target_xyz_d65_cat16.csv"
    source_target_path = output / "synthetic_target_xyz_source.csv"
    tone_path = output / "synthetic_tone_consensus.csv"
    policy_path = output / "synthetic_measurement_policy.csv"
    _write_csv(target_path, ["X", "Y", "Z"], target_xyz_d65)
    _write_csv(source_target_path, ["X", "Y", "Z"], target_xyz_source)
    _write_csv(
        tone_path,
        ["linear", "hlg_path_encoded", "raw_path_encoded", "consensus_encoded"],
        np.column_stack(
            [
                dual_path.linear,
                dual_path.hlg_encoded,
                dual_path.raw_encoded,
                dual_path.consensus_encoded,
            ]
        ),
    )
    _write_measurement_policy_csv(policy_path, policy_linear, measurement_policy)

    report = {
        "pipeline": "log-lut-reconstruction",
        "status": quality["status"],
        "stages": {
            "spectral_targets": {
                "patch_count": config.patch_count,
                "source_white_xyz": source_white.tolist(),
                "destination_white_xyz": D65_WHITE.tolist(),
                "chromatic_adaptation": config.chromatic_adaptation,
                "adaptation_matrix": adaptation.tolist(),
            },
            "spatial_correction": {"flat_field_residual_cv": flat_field_residual_cv},
            "measurement_point_policy": {
                **measurement_policy.summary(),
                "configuration": config.measurement_policy.to_dict(),
            },
            "static_color_calibration": {
                "model": config.color_model,
                "delta_e00": ccm_summary,
            },
            "dual_path_log_reconstruction": dual_path.to_dict(),
            "lut_deployment": {
                "lut_size": config.lut_size,
                "chromatic_adaptation": config.chromatic_adaptation,
                "targets_pre_adapted_to_destination_white": True,
                "spatial_correction": spatial_spec.to_dict(),
                "training_samples_corrected_before_log_encoding": True,
                "in_memory_mean_delta_e00": in_memory_validation["mean_delta_e00"],
                "in_memory_p95_delta_e00": in_memory_validation["p95_delta_e00"],
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
        artifacts=[
            cube_path,
            target_path,
            source_target_path,
            tone_path,
            policy_path,
            report_path,
        ],
        metadata={
            "pipeline": "log-lut-reconstruction",
            "seed": config.seed,
            "status": quality["status"],
            "chromatic_adaptation": config.chromatic_adaptation,
            "measurement_policy": config.measurement_policy.to_dict(),
        },
    )
    return report
