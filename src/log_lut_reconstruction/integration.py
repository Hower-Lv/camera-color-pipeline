from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from .hlg_path import HLGPathResult, fit_hlg_log_path
from .raw_path import RAWPathResult, fit_raw_log_path

if TYPE_CHECKING:
    from log_reconstruction import LogTemplate


@dataclass(frozen=True)
class DualPathResult:
    hlg: HLGPathResult
    raw: RAWPathResult
    linear: np.ndarray
    hlg_encoded: np.ndarray
    raw_encoded: np.ndarray
    consensus_encoded: np.ndarray
    shared_linear_min: float
    shared_linear_max: float
    disagreement_rmse: float

    def to_dict(self) -> dict[str, object]:
        return {
            "hlg_path": self.hlg.to_dict(),
            "raw_path": self.raw.to_dict(),
            "integration": {
                "shared_linear_range": [self.shared_linear_min, self.shared_linear_max],
                "disagreement_rmse": self.disagreement_rmse,
                "consensus": "pointwise mean followed by monotonic accumulation",
            },
        }


def reconstruct_dual_path(
    hlg_luma_code: np.ndarray,
    raw_relative_linear: np.ndarray,
    log_luma_code: np.ndarray,
    *,
    bit_depth: int = 10,
    template: LogTemplate | None = None,
    linear_grid: np.ndarray | None = None,
) -> DualPathResult:
    hlg_result = fit_hlg_log_path(
        hlg_luma_code,
        log_luma_code,
        bit_depth=bit_depth,
        template=template,
    )
    raw_result = fit_raw_log_path(
        raw_relative_linear,
        log_luma_code,
        bit_depth=bit_depth,
        template=template,
    )

    shared_min = max(hlg_result.linear_min, raw_result.linear_min)
    shared_max = min(hlg_result.linear_max, raw_result.linear_max)
    if shared_max <= shared_min:
        raise ValueError("HLG and RAW paths do not share a measured linear domain")

    grid = (
        np.linspace(0.0, 1.0, 513)
        if linear_grid is None
        else np.asarray(linear_grid, dtype=np.float64).reshape(-1)
    )
    if grid.size < 2 or np.any(~np.isfinite(grid)) or np.any(grid < 0.0):
        raise ValueError("linear_grid must contain finite non-negative samples")
    if np.any(np.diff(grid) <= 0.0):
        raise ValueError("linear_grid must be strictly increasing")

    hlg_encoded = hlg_result.predict(grid)
    raw_encoded = raw_result.predict(grid)
    consensus = np.maximum.accumulate((hlg_encoded + raw_encoded) / 2.0)

    shared_grid = np.linspace(shared_min, shared_max, 1025)
    shared_difference = hlg_result.predict(shared_grid) - raw_result.predict(shared_grid)
    disagreement = float(np.sqrt(np.mean(shared_difference**2)))
    return DualPathResult(
        hlg_result,
        raw_result,
        grid,
        hlg_encoded,
        raw_encoded,
        consensus,
        shared_min,
        shared_max,
        disagreement,
    )
