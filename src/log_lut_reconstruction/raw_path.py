from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from log_reconstruction import LogFit, LogTemplate


@dataclass(frozen=True)
class RAWPathResult:
    log_fit: LogFit
    linear_min: float
    linear_max: float
    sample_count: int

    def predict(self, scene_linear: np.ndarray) -> np.ndarray:
        return self.log_fit.predict(scene_linear)

    def to_dict(self) -> dict[str, object]:
        return {
            "path": "raw_log",
            "linear_source": "calibrated RAW relative-linear exposure",
            "linear_range": [self.linear_min, self.linear_max],
            "sample_count": self.sample_count,
            "rmse": self.log_fit.rmse,
        }


def _normalize_limited_luma(code: np.ndarray, bit_depth: int) -> np.ndarray:
    if bit_depth < 8:
        raise ValueError("bit_depth must be at least 8")
    scale = float(1 << (bit_depth - 8))
    black = 16.0 * scale
    white = 235.0 * scale
    return (np.asarray(code, dtype=np.float64) - black) / (white - black)


def fit_raw_log_path(
    raw_relative_linear: np.ndarray,
    log_luma_code: np.ndarray,
    *,
    bit_depth: int = 10,
    template: LogTemplate | None = None,
) -> RAWPathResult:
    try:
        from log_reconstruction import fit_log_template
    except ImportError as exc:
        raise RuntimeError("Install paired-log-reconstruction to fit the RAW path") from exc

    linear = np.asarray(raw_relative_linear, dtype=np.float64).reshape(-1)
    log_normalized = _normalize_limited_luma(log_luma_code, bit_depth).reshape(-1)
    if linear.shape != log_normalized.shape:
        raise ValueError("RAW linear values and Log codes must contain the same samples")
    valid = (
        np.isfinite(linear)
        & np.isfinite(log_normalized)
        & (linear >= 0.0)
        & (log_normalized >= 0.0)
        & (log_normalized <= 1.0)
    )
    if np.count_nonzero(valid) < 8:
        raise ValueError("at least eight valid RAW-Log pairs are required")
    selected_linear = linear[valid]
    fit = fit_log_template(
        selected_linear,
        log_normalized[valid],
        template=template,
    )
    return RAWPathResult(
        fit,
        float(np.min(selected_linear)),
        float(np.max(selected_linear)),
        int(selected_linear.size),
    )
