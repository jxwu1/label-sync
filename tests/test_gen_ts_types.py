"""gen_ts_types — pydantic JSON Schema → TS 的轻量转换（spec §6）。"""

from __future__ import annotations

import subprocess
import sys


def test_generated_ts_contains_models(tmp_path):
    out = tmp_path / "types.gen.ts"
    r = subprocess.run(
        [sys.executable, "tools/gen_ts_types.py", "--out", str(out)],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    ts = out.read_text(encoding="utf-8")
    assert "export interface BriefingData" in ts
    assert "data_week: string | null;" in ts
    assert "cards: BriefingCards;" in ts


def test_check_mode_detects_drift(tmp_path):
    out = tmp_path / "types.gen.ts"
    subprocess.run([sys.executable, "tools/gen_ts_types.py", "--out", str(out)], check=True)
    ok = subprocess.run([sys.executable, "tools/gen_ts_types.py", "--out", str(out), "--check"])
    assert ok.returncode == 0
    out.write_text("// drifted", encoding="utf-8")
    drift = subprocess.run([sys.executable, "tools/gen_ts_types.py", "--out", str(out), "--check"])
    assert drift.returncode != 0
