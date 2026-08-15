from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from log_lut_reconstruction import compare_public_log_templates, encode_public_log


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    output = root / "outputs" / "template_comparison"
    output.mkdir(parents=True, exist_ok=True)
    linear = np.geomspace(1e-4, 1.0, 240)
    black = encode_public_log("oppo_o_log2", np.asarray([0.0]))[0]
    encoded = 0.91 * (encode_public_log("oppo_o_log2", 1.35 * linear) - black)
    capture_ids = [f"capture_{index // 60 + 1}" for index in range(linear.size)]
    report = compare_public_log_templates(linear, encoded, group_ids=capture_ids)
    report_path = output / "synthetic_public_template_comparison.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"best template family: {report['fits'][0]['label']}")
    print(f"report: {report_path}")


if __name__ == "__main__":
    main()
