"""一次性多 run 批跑驱动 (2026-05-19, walk_forward 累积训练 + HW 加速后).

默认跑 5 model × 2 view = 10 run (跳过 HoltWinters; HW 单 view ~3.7h, 性价比差).
加 --include-slow 跑全 6 model = 12 run (季度学术对比时用).
通过 docker cp 进容器, nohup 后台跑.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
import time

from app.services.backtest import BASELINES, run_backtest_all_skus

# HW 单 view ~3.7h, 远超 EmpQuant (~85s); 默认从日常 batch 里排除
_SLOW_MODELS = frozenset({"HoltWinters"})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--include-slow",
        action="store_true",
        help="跑 HoltWinters 等慢模型 (默认跳过, 季度学术对比时打开)",
    )
    args = parser.parse_args()

    end_date = dt.date.today()
    weeks = 156

    all_models = [
        "NaiveMean4W",
        "NaiveSeasonal52W",
        "LinearTrend12W",
        "CrostonSBA",
        "EmpiricalQuantile",
        "HoltWinters",
    ]
    if args.include_slow:
        models = all_models
    else:
        models = [m for m in all_models if m not in _SLOW_MODELS]
    views = ["base_demand", "all"]

    print(f"[batch] start end_date={end_date} weeks={weeks}", flush=True)
    print(f"[batch] include_slow={args.include_slow} models={models}", flush=True)
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
