from __future__ import annotations

from pathlib import Path

from log_lut_reconstruction import PipelineConfig, run_synthetic_pipeline


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    config_path = root / "configs" / "synthetic.toml"
    config = PipelineConfig.from_toml(config_path)
    report = run_synthetic_pipeline(
        config,
        root / "outputs" / "synthetic",
        config_path=config_path,
    )
    print(f"pipeline status: {report['status']}")


if __name__ == "__main__":
    main()
