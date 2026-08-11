from __future__ import annotations

from dataclasses import dataclass, fields
from pathlib import Path
import tomllib


@dataclass(frozen=True)
class QualityThresholds:
    max_flat_field_residual_cv: float = 0.005
    max_ccm_mean_delta_e00: float = 0.25
    max_method_a_rmse: float = 0.001
    max_method_b_rmse: float = 0.001
    max_tone_consensus_rmse: float = 0.001
    max_lut_mean_delta_e00: float = 1.0
    max_lut_p95_delta_e00: float = 2.0
    max_gray_reverse_steps: int = 0
    max_gray_channel_spread: float = 1e-6


@dataclass(frozen=True)
class PipelineConfig:
    seed: int = 2026
    patch_count: int = 30
    pair_sample_count: int = 4096
    capture_count: int = 3
    log_curvature: float = 24.0
    color_model: str = "3x9"
    ridge: float = 1e-5
    lut_size: int = 17
    neutral_width_cells: int = 1
    quality: QualityThresholds = QualityThresholds()

    @classmethod
    def from_toml(cls, path: str | Path) -> PipelineConfig:
        with Path(path).open("rb") as handle:
            data = tomllib.load(handle)
        pipeline = data.get("pipeline", {})
        quality_data = data.get("quality", {})
        allowed_pipeline = {field.name for field in fields(cls)} - {"quality"}
        allowed_quality = {field.name for field in fields(QualityThresholds)}
        unknown_pipeline = set(pipeline) - allowed_pipeline
        unknown_quality = set(quality_data) - allowed_quality
        if unknown_pipeline or unknown_quality:
            raise ValueError(
                f"unknown configuration keys: pipeline={sorted(unknown_pipeline)}, "
                f"quality={sorted(unknown_quality)}"
            )
        return cls(**pipeline, quality=QualityThresholds(**quality_data))

    def validate(self) -> None:
        if self.patch_count < 12:
            raise ValueError("patch_count must be at least 12")
        if self.pair_sample_count < 32:
            raise ValueError("pair_sample_count must be at least 32")
        if self.capture_count < 2:
            raise ValueError("capture_count must be at least 2")
        if self.log_curvature <= 0:
            raise ValueError("log_curvature must be positive")
        if self.color_model not in {"3x3", "3x7", "3x9"}:
            raise ValueError("color_model must be 3x3, 3x7 or 3x9")
        if self.ridge < 0:
            raise ValueError("ridge cannot be negative")
        if self.lut_size < 2:
            raise ValueError("lut_size must be at least 2")
        if self.neutral_width_cells < 0:
            raise ValueError("neutral_width_cells cannot be negative")
