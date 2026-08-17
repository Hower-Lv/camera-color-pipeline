from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from log_reconstruction import LogFit, LogTemplate


@dataclass(frozen=True)
class HLGPathResult:
    log_fit: LogFit
    linear_min: float
    linear_max: float
    sample_count: int

    def predict(self, scene_linear: np.ndarray) -> np.ndarray:
        return self.log_fit.predict(scene_linear)

    def to_dict(self) -> dict[str, object]:
        return {
            "path": "hlg_log",
            "linear_source": "HLG inverse OETF",
            "linear_range": [self.linear_min, self.linear_max],
            "sample_count": self.sample_count,
            "rmse": self.log_fit.rmse,
        }


def fit_hlg_log_path(
    hlg_luma_code: np.ndarray,
    log_luma_code: np.ndarray,
    *,
    bit_depth: int = 10,
    template: LogTemplate | None = None,
) -> HLGPathResult:
    try:
        from log_reconstruction import fit_hlg_log_pair
    except ImportError as exc:
        raise RuntimeError("Install paired-log-reconstruction to fit the HLG path") from exc

    result = fit_hlg_log_pair(
        hlg_luma_code,
        log_luma_code,
        bit_depth=bit_depth,
        template=template,
    )
    return HLGPathResult(
        result.log_fit,
        result.hlg_linear_min,
        result.hlg_linear_max,
        result.log_fit.sample_count,
    )
