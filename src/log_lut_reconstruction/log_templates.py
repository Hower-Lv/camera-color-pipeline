from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class PublicLogTemplate:
    key: str
    label: str
    reference: str
    valid_min: float = 0.0

    def encode(self, scene_linear: np.ndarray) -> np.ndarray:
        return encode_public_log(self.key, scene_linear)


@dataclass(frozen=True)
class PublicLogFit:
    template: PublicLogTemplate
    input_scale: float
    output_gain: float
    output_offset: float
    rmse: float
    max_abs_error: float
    sample_count: int
    leave_group_out_rmse: float | None = None
    validation_group_count: int = 0

    def predict(self, scene_linear: np.ndarray) -> np.ndarray:
        values = np.asarray(scene_linear, dtype=np.float64)
        black = float(self.template.encode(np.asarray([0.0]))[0])
        shaped = self.template.encode(self.input_scale * values) - black
        return self.output_offset + self.output_gain * shaped

    def to_dict(self) -> dict[str, object]:
        return {
            "template": self.template.key,
            "label": self.template.label,
            "reference": self.template.reference,
            "input_scale": self.input_scale,
            "output_gain": self.output_gain,
            "output_offset": self.output_offset,
            "rmse": self.rmse,
            "max_abs_error": self.max_abs_error,
            "sample_count": self.sample_count,
            "leave_group_out_rmse": self.leave_group_out_rmse,
            "validation_group_count": self.validation_group_count,
        }


PUBLIC_LOG_TEMPLATES: dict[str, PublicLogTemplate] = {
    "dji_d_log": PublicLogTemplate(
        "dji_d_log",
        "DJI D-Log",
        "DJI D-Log and D-Gamut white paper",
    ),
    "insta360_i_log": PublicLogTemplate(
        "insta360_i_log",
        "Insta360 I-Log",
        "Insta360 I-Log published transfer constants",
    ),
    "oppo_o_log2": PublicLogTemplate(
        "oppo_o_log2",
        "OPPO O-Log2",
        "OPPO O-Log2 published transfer constants",
    ),
    "arri_logc4": PublicLogTemplate(
        "arri_logc4",
        "ARRI LogC4",
        "ARRI LogC4 specification",
    ),
    "sony_s_log3": PublicLogTemplate(
        "sony_s_log3",
        "Sony S-Log3",
        "Sony S-Log3 technical summary",
    ),
    "panasonic_v_log": PublicLogTemplate(
        "panasonic_v_log",
        "Panasonic V-Log",
        "Panasonic V-Log/V-Gamut reference manual",
    ),
}


def encode_public_log(key: str, scene_linear: np.ndarray) -> np.ndarray:
    values = np.asarray(scene_linear, dtype=np.float64)
    if np.any(~np.isfinite(values)) or np.any(values < 0.0):
        raise ValueError("scene_linear must contain finite non-negative values")
    if key == "dji_d_log":
        return np.where(
            values <= 0.0078,
            6.025 * values + 0.0929,
            (np.log10(0.9892 * values + 0.0108) + 2.27752) / 3.89616,
        )
    if key == "insta360_i_log":
        transition = (0.154402 - 0.09055934) / 5.77837328
        return np.where(
            values < transition,
            5.77837328 * values + 0.09055934,
            0.280055 * np.log10(values + 0.01) + 0.623992,
        )
    if key == "oppo_o_log2":
        return 0.0855 * np.log2(values + 0.0096) + 0.693
    if key == "arri_logc4":
        a = 2231.8263090676883
        b = 0.9071358748778103
        c = 0.09286412512218964
        return ((np.log2(a * values + 64.0) - 6.0) / 14.0) * b + c
    if key == "sony_s_log3":
        low = (values * (171.2102946929 - 95.0) / 0.01125 + 95.0) / 1023.0
        high = (
            420.0 + np.log10((values + 0.01) / (0.18 + 0.01)) * 261.5
        ) / 1023.0
        return np.where(values >= 0.01125, high, low)
    if key == "panasonic_v_log":
        return np.where(
            values < 0.01,
            5.6 * values + 0.125,
            0.241514 * np.log10(values + 0.00873) + 0.598206,
        )
    raise KeyError(f"unknown public Log template: {key}")


def _validate_samples(
    scene_linear: np.ndarray, encoded: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    linear = np.asarray(scene_linear, dtype=np.float64).reshape(-1)
    target = np.asarray(encoded, dtype=np.float64).reshape(-1)
    valid = np.isfinite(linear) & np.isfinite(target) & (linear >= 0.0)
    linear = linear[valid]
    target = target[valid]
    if linear.size < 8:
        raise ValueError("at least eight valid paired samples are required")
    return linear, target


def fit_public_log_template(
    scene_linear: np.ndarray,
    encoded: np.ndarray,
    template_key: str,
    *,
    fit_offset: bool = False,
    scale_bounds: tuple[float, float] = (1e-4, 1e4),
) -> PublicLogFit:
    linear, target = _validate_samples(scene_linear, encoded)
    if template_key not in PUBLIC_LOG_TEMPLATES:
        raise KeyError(f"unknown public Log template: {template_key}")
    if scale_bounds[0] <= 0.0 or scale_bounds[1] <= scale_bounds[0]:
        raise ValueError("scale_bounds must be positive and increasing")
    template = PUBLIC_LOG_TEMPLATES[template_key]
    black = float(template.encode(np.asarray([0.0]))[0])
    lower, upper = np.log(scale_bounds)
    best: tuple[float, float, float, np.ndarray] | None = None
    for _ in range(5):
        log_scales = np.linspace(lower, upper, 161)
        for log_scale in log_scales:
            scale = float(np.exp(log_scale))
            shaped = template.encode(scale * linear) - black
            if fit_offset:
                design = np.column_stack([shaped, np.ones_like(shaped)])
                gain, offset = np.linalg.lstsq(design, target, rcond=None)[0]
            else:
                denominator = float(shaped @ shaped)
                gain = float(shaped @ target / denominator) if denominator > 0.0 else -1.0
                offset = 0.0
            if gain <= 0.0:
                continue
            residual = gain * shaped + offset - target
            score = float(np.mean(residual**2))
            if best is None or score < best[0]:
                best = score, scale, float(gain), np.asarray([offset], dtype=np.float64)
        if best is None:
            raise RuntimeError("unable to fit a positive-gain Log template")
        step = (upper - lower) / 160.0
        center = np.log(best[1])
        lower, upper = center - 4.0 * step, center + 4.0 * step
    assert best is not None
    _, scale, gain, offset_array = best
    offset = float(offset_array[0])
    prediction = offset + gain * (template.encode(scale * linear) - black)
    residual = prediction - target
    return PublicLogFit(
        template,
        scale,
        gain,
        offset,
        float(np.sqrt(np.mean(residual**2))),
        float(np.max(np.abs(residual))),
        int(linear.size),
    )


def _leave_group_out_rmse(
    scene_linear: np.ndarray,
    encoded: np.ndarray,
    groups: np.ndarray,
    template_key: str,
    fit_offset: bool,
) -> tuple[float | None, int]:
    residuals: list[np.ndarray] = []
    valid_groups = 0
    for group in sorted(set(groups.tolist()), key=str):
        validation = groups == group
        training = ~validation
        if np.count_nonzero(training) < 8 or not np.any(validation):
            continue
        fit = fit_public_log_template(
            scene_linear[training],
            encoded[training],
            template_key,
            fit_offset=fit_offset,
        )
        residuals.append(fit.predict(scene_linear[validation]) - encoded[validation])
        valid_groups += 1
    if not residuals:
        return None, 0
    combined = np.concatenate(residuals)
    return float(np.sqrt(np.mean(combined**2))), valid_groups


def compare_public_log_templates(
    scene_linear: np.ndarray,
    encoded: np.ndarray,
    *,
    template_keys: Iterable[str] | None = None,
    group_ids: Iterable[object] | None = None,
    fit_offset: bool = False,
) -> dict[str, object]:
    raw_linear = np.asarray(scene_linear, dtype=np.float64).reshape(-1)
    raw_target = np.asarray(encoded, dtype=np.float64).reshape(-1)
    if raw_linear.shape != raw_target.shape:
        raise ValueError("scene_linear and encoded must contain the same number of samples")
    valid = np.isfinite(raw_linear) & np.isfinite(raw_target) & (raw_linear >= 0.0)
    linear, target = _validate_samples(raw_linear, raw_target)
    keys = list(template_keys or PUBLIC_LOG_TEMPLATES)
    groups = None if group_ids is None else np.asarray(list(group_ids), dtype=object).reshape(-1)
    if groups is not None:
        if groups.shape != raw_linear.shape:
            raise ValueError("group_ids must contain one value per input sample")
        groups = groups[valid]
    fits: list[PublicLogFit] = []
    for key in keys:
        fit = fit_public_log_template(linear, target, key, fit_offset=fit_offset)
        if groups is not None:
            group_rmse, group_count = _leave_group_out_rmse(
                linear, target, groups, key, fit_offset
            )
            fit = PublicLogFit(
                fit.template,
                fit.input_scale,
                fit.output_gain,
                fit.output_offset,
                fit.rmse,
                fit.max_abs_error,
                fit.sample_count,
                group_rmse,
                group_count,
            )
        fits.append(fit)
    fits.sort(
        key=lambda item: (
            item.leave_group_out_rmse is None,
            item.leave_group_out_rmse if item.leave_group_out_rmse is not None else item.rmse,
            item.rmse,
        )
    )
    grid = np.linspace(float(np.min(linear)), float(np.max(linear)), 1025)
    pairwise = []
    for first_index, first in enumerate(fits):
        for second in fits[first_index + 1 :]:
            difference = np.abs(first.predict(grid) - second.predict(grid))
            pairwise.append(
                {
                    "first": first.template.key,
                    "second": second.template.key,
                    "max_abs_difference": float(np.max(difference)),
                    "rmse_difference": float(np.sqrt(np.mean(difference**2))),
                }
            )
    return {
        "sample_count": int(linear.size),
        "measured_linear_range": [float(np.min(linear)), float(np.max(linear))],
        "fit_offset": fit_offset,
        "ranking_metric": "leave_group_out_rmse" if groups is not None else "rmse",
        "fits": [fit.to_dict() for fit in fits],
        "pairwise_curve_differences": pairwise,
        "claim_boundary": (
            "The ranking identifies empirical shape agreement inside the measured domain; "
            "it does not identify the manufacturer's internal OETF."
        ),
    }
