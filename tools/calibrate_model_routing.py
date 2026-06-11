"""模型路由标定脚本 (ADR-0002 D6)。

任何 新增 SKU 类别 / 改 categorizer 阈值 / 换主力模型 的 PR，先重跑本脚本，
把输出贴进 PR 描述 —— "以后新增类别直接查表不用重新推理" 的机制本体。

用法 (本地 PG 镜像):
    DATABASE_URL=postgresql+psycopg://dev:devpass@localhost:5433/label_sync \
        python tools/calibrate_model_routing.py

输出:
    1. ADI×CV² 象限分布 (Syntetos-Boylan 切点 1.32/0.49 仅作分格, 结论看格内实证)
    2. 象限 × 模型 → medMASE / avgCov@98 / medBias 交叉表 (最新 runs)
    3. 非 retail/mixed 子集 (wholesale 代理) 模型对比
首次标定结论 (2026-06-11) 见 docs/adr/0002-model-selection.md。
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import numpy as np
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import get_session  # noqa: E402

_ADI_CV2_SQL = """
with weekly as (
  select product_barcode bc, date_trunc('week', event_at::date)::date wk, sum(qty) q
  from inventory_events
  where event_type='sale' and event_at >= (current_date - interval '156 weeks')::text
  group by 1,2
),
pos as (select * from weekly where q > 0),
stats as (
  select bc,
         count(*) nzw,
         ((max(wk) - min(wk))/7 + 1) span_w,
         avg(q) mean_q,
         coalesce(stddev_samp(q), 0) sd_q
  from pos group by bc
)
select bc,
       span_w::float / nzw as adi,
       case when mean_q > 0 then power(sd_q / mean_q, 2) else null end as cv2
from stats
where nzw >= 5 and span_w >= 20
"""

_LATEST_RUNS_SQL = """
select r.id, r.model_name, r.view from backtest_runs r
join (select model_name, view, max(id) mid from backtest_runs group by 1,2) t on t.mid = r.id
"""

_RESULTS_SQL = """
select product_barcode, mase, coverage_p98, bias from backtest_results where run_id = :rid
"""


def quadrant(adi: float, cv2: float) -> str:
    if adi < 1.32:
        return "smooth" if cv2 < 0.49 else "erratic"
    return "intermittent" if cv2 < 0.49 else "lumpy"


def main() -> None:
    with get_session() as s:
        rows = s.execute(text(_ADI_CV2_SQL)).all()
        runs = s.execute(text(_LATEST_RUNS_SQL)).all()
        typed = dict(s.execute(text("select product_barcode, sku_type from forecast_output")).all())

        qd = {r.bc: quadrant(float(r.adi), float(r.cv2)) for r in rows if r.cv2 is not None}
        print(f"SKU 可标定 (非零周>=5, 跨度>=20w): {len(qd)}")
        print("\n=== 象限分布 ===")
        for k, v in Counter(qd.values()).most_common():
            print(f"  {k:14s} {v:6d}  {v / len(qd) * 100:.1f}%")
        adis = sorted(float(r.adi) for r in rows)
        print(
            "  ADI p10/p50/p90: " + "/".join(f"{x:.2f}" for x in np.quantile(adis, [0.1, 0.5, 0.9]))
        )

        for view in ("base_demand", "all"):
            per_model: dict[str, dict] = {}
            for r in runs:
                if r.view != view:
                    continue
                res = s.execute(text(_RESULTS_SQL), {"rid": r.id}).all()
                per_model[r.model_name] = {
                    x.product_barcode: (x.mase, x.coverage_p98, x.bias) for x in res
                }
            if not per_model:
                continue
            print(f"\n========== view = {view} ==========")
            print(
                f"{'quadrant':14s} {'model':18s} {'n':>5s} {'medMASE':>8s} "
                f"{'avgCov98':>9s} {'medBias':>8s}"
            )
            for quad in ("smooth", "erratic", "intermittent", "lumpy"):
                bcs = {bc for bc, q in qd.items() if q == quad}
                for m, res in sorted(per_model.items()):
                    vals = [
                        res[bc]
                        for bc in bcs
                        if bc in res and res[bc][0] is not None and not np.isnan(res[bc][0])
                    ]
                    if len(vals) < 20:
                        continue
                    mases = [x[0] for x in vals]
                    covs = [x[1] for x in vals if x[1] is not None]
                    biases = [x[2] for x in vals if x[2] is not None]
                    print(
                        f"{quad:14s} {m:18s} {len(vals):5d} {np.median(mases):8.3f} "
                        f"{np.mean(covs) if covs else float('nan'):9.3f} "
                        f"{np.median(biases) if biases else float('nan'):8.3f}"
                    )
            if view == "all":
                print("\n  --- 非 retail/mixed 子集 (wholesale 代理) ---")
                for m, res in sorted(per_model.items()):
                    sub = [
                        v
                        for bc, v in res.items()
                        if bc not in typed and v[0] is not None and not np.isnan(v[0])
                    ]
                    if len(sub) < 20:
                        print(f"  {m:18s} n={len(sub)} (<20, 样本不足)")
                        continue
                    mases = [x[0] for x in sub]
                    covs = [x[1] for x in sub if x[1] is not None]
                    print(
                        f"  {m:18s} n={len(sub):5d} medMASE={np.median(mases):.3f} "
                        f"avgCov98={np.mean(covs) if covs else float('nan'):.3f}"
                    )


if __name__ == "__main__":
    main()
