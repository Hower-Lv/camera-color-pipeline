from __future__ import annotations

import numpy as np

CAT16_MATRIX = np.asarray(
    [
        [0.401288, 0.650173, -0.051461],
        [-0.250268, 1.204414, 0.045854],
        [-0.002079, 0.048952, 0.953127],
    ],
    dtype=np.float64,
)


def cat16_adaptation(source_white: np.ndarray, destination_white: np.ndarray) -> np.ndarray:
    source = np.asarray(source_white, dtype=np.float64)
    destination = np.asarray(destination_white, dtype=np.float64)
    if source.shape != (3,) or destination.shape != (3,):
        raise ValueError("white points must have shape (3,)")
    if np.any(~np.isfinite(source)) or np.any(~np.isfinite(destination)):
        raise ValueError("white points must be finite")
    source_cone = CAT16_MATRIX @ source
    destination_cone = CAT16_MATRIX @ destination
    if np.any(np.abs(source_cone) < 1e-12):
        raise ValueError("source white produces a zero CAT16 cone response")
    return (
        np.linalg.inv(CAT16_MATRIX)
        @ np.diag(destination_cone / source_cone)
        @ CAT16_MATRIX
    )
