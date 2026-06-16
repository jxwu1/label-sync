"""build_briefing_cached 拆分缓存测试。

设计: 重核心 (sales_health/sku_summary 卡片/review) 按 (data_week, MAX(event.id) 数据版本)
缓存; follow_up(逾期) 和 data_health(距今) 日期敏感且便宜 → 每次现算保新鲜, 不进缓存。
- 同数据版本+数据周 → 核心命中不重算 (解决「每次首载 12s」); 叠加块仍每次现算。
- 新导入(版本变) / 数据周变 / 超 TTL → 核心重算。
build_briefing 本体保持纯全量不缓存, 既有 service 测试不受影响。
"""

from datetime import date

import pytest

from app.services import briefing


@pytest.fixture
def patched(monkeypatch):
    """打桩重核心 + 叠加块, 计数调用次数; 返回 counts dict。"""
    counts = {"core": 0, "data_health": 0, "follow_up": 0}

    def fake_core(data_week, complete):
        counts["core"] += 1
        return {
            "rows": [],
            "cards": {
                "sales_health": {"ok": True, "n": counts["core"]},
                "restock_risk": {"ok": True},
                "stockout_impact": {"ok": True},
                "overstock_risk": {"ok": True},
            },
            "restock_action": {"ok": True},
            "review_action": {"ok": True},
        }

    def fake_dh(rows):
        counts["data_health"] += 1
        return {"ok": True, "n": counts["data_health"]}

    def fake_fu(as_of):
        counts["follow_up"] += 1
        return {"ok": True, "n": counts["follow_up"]}

    monkeypatch.setattr(briefing, "_compute_core", fake_core)
    monkeypatch.setattr(briefing, "compute_data_health", fake_dh)
    monkeypatch.setattr(briefing, "build_follow_up_actions", fake_fu)
    monkeypatch.setattr(briefing, "_resolve_data_week", lambda as_of: (date(2026, 6, 8), True))
    monkeypatch.setattr(briefing, "_data_version", lambda: 100)
    briefing.reset_briefing_cache()
    return counts, monkeypatch


def test_core_cached_overlay_fresh(patched):
    counts, _ = patched
    p1 = briefing.build_briefing_cached(date(2026, 6, 16), "g1")
    p2 = briefing.build_briefing_cached(date(2026, 6, 16), "g2")
    assert counts["core"] == 1  # 重核心只算一次
    assert counts["data_health"] == 2  # 叠加每次现算
    assert counts["follow_up"] == 2
    # generated_at 每次现取 (不是缓存的旧值)
    assert p1["generated_at"] == "g1"
    assert p2["generated_at"] == "g2"


def test_payload_shape(patched):
    counts, _ = patched
    p = briefing.build_briefing_cached(date(2026, 6, 16), "g1")
    assert p["ok"] is True
    assert p["data_week"] == "2026-06-08"
    assert set(p["cards"]) == {
        "sales_health",
        "restock_risk",
        "stockout_impact",
        "overstock_risk",
        "data_health",
    }
    assert set(p["actions"]) == {"restock", "follow_up", "review_anomalies"}
    assert p["cards"]["data_health"]["ok"] is True
    assert p["actions"]["follow_up"]["ok"] is True


def test_core_busts_on_new_data(patched):
    counts, monkeypatch = patched
    versions = iter([1, 2])
    monkeypatch.setattr(briefing, "_data_version", lambda: next(versions))
    briefing.build_briefing_cached(date(2026, 6, 16), "g1")
    briefing.build_briefing_cached(date(2026, 6, 16), "g2")
    assert counts["core"] == 2  # 数据版本变 → 重核心重算


def test_core_busts_on_data_week(patched):
    counts, monkeypatch = patched
    weeks = iter([(date(2026, 6, 8), True), (date(2026, 6, 15), True)])
    monkeypatch.setattr(briefing, "_resolve_data_week", lambda as_of: next(weeks))
    briefing.build_briefing_cached(date(2026, 6, 16), "g1")
    briefing.build_briefing_cached(date(2026, 6, 17), "g2")
    assert counts["core"] == 2  # 数据周变 → 重核心重算


def test_core_busts_on_ttl(patched):
    counts, monkeypatch = patched
    clock = {"t": 1000.0}
    monkeypatch.setattr(briefing, "_now", lambda: clock["t"])
    briefing.build_briefing_cached(date(2026, 6, 16), "g1", ttl=300)
    clock["t"] += 301
    briefing.build_briefing_cached(date(2026, 6, 16), "g2", ttl=300)
    assert counts["core"] == 2  # 超 TTL → 重核心重算


def test_core_hit_within_ttl(patched):
    counts, monkeypatch = patched
    clock = {"t": 1000.0}
    monkeypatch.setattr(briefing, "_now", lambda: clock["t"])
    briefing.build_briefing_cached(date(2026, 6, 16), "g1", ttl=300)
    clock["t"] += 120  # < ttl
    briefing.build_briefing_cached(date(2026, 6, 16), "g2", ttl=300)
    assert counts["core"] == 1  # TTL 内 → 核心命中
    assert counts["follow_up"] == 2  # 叠加仍每次现算


def test_prewarm_briefing_warms_cache(monkeypatch):
    """prewarm_briefing 用当天日期调 build_briefing_cached 一次 (导入/部署后暖核心)。"""
    calls = {"n": 0, "as_of": None}

    def fake_cached(as_of, generated_at, **kw):
        calls["n"] += 1
        calls["as_of"] = as_of
        return {"ok": True}

    monkeypatch.setattr(briefing, "build_briefing_cached", fake_cached)
    briefing.prewarm_briefing()
    assert calls["n"] == 1
    assert isinstance(calls["as_of"], date)


def test_prewarm_briefing_swallows_errors(monkeypatch):
    """预热失败不得冒泡 (不能拖垮导入/启动流程)。"""

    def boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(briefing, "build_briefing_cached", boom)
    briefing.prewarm_briefing()  # 不抛即通过
