from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

import numpy as np


class MeasurementKind(StrEnum):
    BLACK_ANCHOR = "black_anchor"
    CONTROLLED_EXPOSURE = "controlled_exposure"
    LOCAL_WHITE_GRADIENT = "local_white_gradient"
    PAIRED_TRANSFER = "paired_transfer"


@dataclass(frozen=True)
class MeasurementPolicyConfig:
    black_anchor: str = "bypass"
    controlled_exposure: str = "linear_x_only"
    local_white_gradient: str = "bypass_preserve_gradient"
    paired_transfer: str = "bypass_same_position"
    image_spatial_correction: str = "linear_before_lut"
    geometry_id: str = "fixed_capture_geometry"

    def validate(self) -> None:
        expected = {
            "black_anchor": "bypass",
            "controlled_exposure": "linear_x_only",
            "local_white_gradient": "bypass_preserve_gradient",
            "paired_transfer": "bypass_same_position",
            "image_spatial_correction": "linear_before_lut",
        }
        for field_name, expected_value in expected.items():
            if getattr(self, field_name) != expected_value:
                raise ValueError(
                    f"{field_name} must be {expected_value!r} under the selective flat-field policy"
                )
        if not self.geometry_id.strip():
            raise ValueError("geometry_id cannot be empty")

    def to_dict(self) -> dict[str, str]:
        return {
            "black_anchor": self.black_anchor,
            "controlled_exposure": self.controlled_exposure,
            "local_white_gradient": self.local_white_gradient,
            "paired_transfer": self.paired_transfer,
            "image_spatial_correction": self.image_spatial_correction,
            "geometry_id": self.geometry_id,
        }


@dataclass(frozen=True)
class MeasurementPolicyResult:
    linear: np.ndarray
    encoded: np.ndarray
    kinds: np.ndarray
    spatial_factors: np.ndarray

    def summary(self) -> dict[str, object]:
        groups = []
        for kind in MeasurementKind:
            selected = self.kinds == kind.value
            if not np.any(selected):
                continue
            factors = self.spatial_factors[selected]
            groups.append(
                {
                    "kind": kind.value,
                    "sample_count": int(np.count_nonzero(selected)),
                    "action": _action_for_kind(kind),
                    "spatial_factor_range": [float(np.min(factors)), float(np.max(factors))],
                    "encoded_values_modified": False,
                }
            )
        return {"policy": "selective_flat_field_v1", "groups": groups}


@dataclass(frozen=True)
class SpatialCorrectionSpec:
    geometry_id: str
    input_domain: str = "linear"
    stage: str = "before_lut"
    embedded_in_cube: bool = False

    def validate(self) -> None:
        if not self.geometry_id.strip():
            raise ValueError("geometry_id cannot be empty")
        if self.input_domain != "linear":
            raise ValueError("RAW-derived multiplicative flat fields require linear input")
        if self.stage != "before_lut":
            raise ValueError("spatial correction must run before LUT construction or application")
        if self.embedded_in_cube:
            raise ValueError(
                "a position-dependent spatial correction cannot be embedded in a 3D LUT"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "geometry_id": self.geometry_id,
            "input_domain": self.input_domain,
            "stage": self.stage,
            "embedded_in_cube": self.embedded_in_cube,
        }


def _action_for_kind(kind: MeasurementKind) -> str:
    return {
        MeasurementKind.BLACK_ANCHOR: "bypass",
        MeasurementKind.CONTROLLED_EXPOSURE: "multiply_linear_x_only",
        MeasurementKind.LOCAL_WHITE_GRADIENT: "bypass_preserve_measured_gradient",
        MeasurementKind.PAIRED_TRANSFER: "bypass_preserve_same_position_pair",
    }[kind]


def apply_selective_measurement_policy(
    linear: np.ndarray,
    encoded: np.ndarray,
    kinds: Iterable[str | MeasurementKind],
    *,
    spatial_factors: np.ndarray | None = None,
) -> MeasurementPolicyResult:
    source_linear = np.asarray(linear, dtype=np.float64).reshape(-1)
    source_encoded = np.asarray(encoded, dtype=np.float64).reshape(-1)
    kind_values = np.asarray([MeasurementKind(item).value for item in kinds], dtype=object)
    if source_linear.shape != source_encoded.shape or source_linear.shape != kind_values.shape:
        raise ValueError("linear, encoded and kinds must contain the same number of samples")
    if np.any(~np.isfinite(source_linear)) or np.any(source_linear < 0.0):
        raise ValueError("linear values must be finite and non-negative")
    if np.any(~np.isfinite(source_encoded)):
        raise ValueError("encoded values must be finite")

    factors = (
        np.ones_like(source_linear)
        if spatial_factors is None
        else np.asarray(spatial_factors, dtype=np.float64).reshape(-1)
    )
    invalid_factors = np.any(~np.isfinite(factors)) or np.any(factors <= 0.0)
    if factors.shape != source_linear.shape or invalid_factors:
        raise ValueError("spatial_factors must be finite, positive and aligned with the samples")

    controlled = kind_values == MeasurementKind.CONTROLLED_EXPOSURE.value
    bypassed = ~controlled
    if np.any(np.abs(factors[bypassed] - 1.0) > 1e-12):
        raise ValueError("spatial factors are only valid for controlled_exposure samples")
    black = kind_values == MeasurementKind.BLACK_ANCHOR.value
    if np.any(np.abs(source_linear[black]) > 1e-12):
        raise ValueError("black_anchor samples must use linear x=0")

    corrected_linear = source_linear.copy()
    corrected_linear[controlled] *= factors[controlled]
    return MeasurementPolicyResult(
        corrected_linear,
        source_encoded.copy(),
        kind_values,
        factors.copy(),
    )


def apply_spatial_correction_before_lut(
    linear_image: np.ndarray,
    flat_field_model: object,
    spec: SpatialCorrectionSpec,
    *,
    actual_geometry_id: str,
) -> np.ndarray:
    spec.validate()
    if actual_geometry_id != spec.geometry_id:
        raise ValueError(
            f"flat-field geometry mismatch: expected {spec.geometry_id!r}, "
            f"received {actual_geometry_id!r}"
        )
    image = np.asarray(linear_image, dtype=np.float64)
    if image.ndim not in (2, 3) or np.any(~np.isfinite(image)) or np.any(image < 0.0):
        raise ValueError("linear_image must be a finite non-negative HxW or HxWxC array")
    try:
        from spectral_color_calibrator import apply_flat_field
    except ImportError as exc:
        raise RuntimeError(
            "Install spectral-color-calibrator to apply image-domain spatial correction"
        ) from exc
    return apply_flat_field(image, flat_field_model)
