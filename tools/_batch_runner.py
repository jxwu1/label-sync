"""一次性 12-run 批跑驱动 (2026-05-19, walk_forward 累积训练 + HW 加速后).

12 runs = 6 models × 2 views (base_demand + all).
跑完后 backtest_runs 多 12 条, backtest_results 增 ~10-15 万行.
不进 repo 工作流, 用完即删. 通过 docker cp 进容器, nohup 后台跑.
"""

from __future__ import annotations

import datetime as dt
import sys
import time

from app.services.backtest import BASELINES, run_backtest_all_skus


def main() -> int:
    end_date = dt.date.today()
    weeks = 156

    models = [
        "NaiveMean4W",
        "NaiveSeasonal52W",
        "LinearTrend12W",
        "CrostonSBA",
        "EmpiricalQuantile",
        "HoltWinters",
    ]
    views = ["base_demand", "all"]

    print(f"[batch] start end_date={end_date} weeks={weeks}", flush=True)
    print(f"[batch] models={models}", flush=True)
    print(f"[batch] BASELINES keys={list(BASELINES)}", flush=True)

    for model_name in models:
        if model_name not in BASELINES:
            print(f"[batch] SKIP {model_name}: not in BASELINES", flush=True)
            continue
        for view in views:
            t0 = time.monotonic()
            print(f"[batch] >>> {model_name} / {view} start", flush=True)
            try:
                run_id = run_backtest_all_skus(
                    model_name=model_name,
                    end_date=end_date,
                    weeks=weeks,
                    view=view,
                    notes="2026-05-19 expanding-window + HW-fast batch",
                )
                dt_s = time.monotonic() - t0
                print(
                    f"[batch] <<< {model_name} / {view} run_id={run_id} ok ({dt_s:.1f}s)",
                    flush=True,
                )
            except Exception as exc:  # noqa: BLE001
                dt_s = time.monotonic() - t0
                print(
                    f"[batch] !!! {model_name} / {view} FAILED ({dt_s:.1f}s): {exc!r}",
                    flush=True,
                )

    print("[batch] all done", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
