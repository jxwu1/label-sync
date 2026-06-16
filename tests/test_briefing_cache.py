"""build_briefing_cached 缓存层测试。

缓存 key = (as_of 日期, MAX(InventoryEvent.id) 数据版本) + TTL 兜底:
- 同日 + 无新事件 → 命中, 不重算 (解决「每次加载 12s」)。
- 新导入 (max id 变) / 跨日 / 超 TTL → 失效重算。
build_briefing 本体保持纯函数 (不缓存), 既有 service 测试不受影响。
"""

from datetime import date

from app.services import briefing


def _counting_build():
    state = {"n": 0}

    def fake(as_of, generated_at):
        state["n"] += 1
        return {"ok": True, "n": state["n"], "generated_at": generated_at}

    return state, fake


def test_cache_hit_skips_recompute(monkeypatch):
    state, fake = _counting_build()
    monkeypatch.setattr(briefing, "build_briefing", fake)
    monkeypatch.setattr(briefing, "_data_version", lambda: 100)
    briefing.reset_briefing_cache()

    a = briefing.build_briefing_cached(date(2026, 6, 16), "g1")
    b = briefing.build_briefing_cached(date(2026, 6, 16), "g2")

    assert state["n"] == 1  # 只算一次
    assert a is b  # 第二次返回同一缓存对象 (含原 generated_at)


def test_cache_busts_on_new_event_data(monkeypatch):
    state, fake = _counting_build()
    monkeypatch.setattr(briefing, "build_briefing", fake)
    versions = iter([1, 2])
    monkeypatch.setattr(briefing, "_data_version", lambda: next(versions))
    briefing.reset_briefing_cache()

    briefing.build_briefing_cached(date(2026, 6, 16), "g1")
    briefing.build_briefing_cached(date(2026, 6, 16), "g2")

    assert state["n"] == 2  # max id 变 → 重算


def test_cache_busts_on_new_day(monkeypatch):
    state, fake = _counting_build()
    monkeypatch.setattr(briefing, "build_briefing", fake)
    monkeypatch.setattr(briefing, "_data_version", lambda: 5)
    briefing.reset_briefing_cache()

    briefing.build_briefing_cached(date(2026, 6, 16), "g1")
    briefing.build_briefing_cached(date(2026, 6, 17), "g2")

    assert state["n"] == 2  # 跨日 → 重算


def test_cache_expires_after_ttl(monkeypatch):
    state, fake = _counting_build()
    monkeypatch.setattr(briefing, "build_briefing", fake)
    monkeypatch.setattr(briefing, "_data_version", lambda: 9)
    clock = {"t": 1000.0}
    monkeypatch.setattr(briefing, "_now", lambda: clock["t"])
    briefing.reset_briefing_cache()

    briefing.build_briefing_cached(date(2026, 6, 16), "g1", ttl=300)
    clock["t"] += 301
    briefing.build_briefing_cached(date(2026, 6, 16), "g2", ttl=300)

    assert state["n"] == 2  # 超 TTL → 重算


def test_cache_hit_within_ttl(monkeypatch):
    state, fake = _counting_build()
    monkeypatch.setattr(briefing, "build_briefing", fake)
    monkeypatch.setattr(briefing, "_data_version", lambda: 9)
    clock = {"t": 1000.0}
    monkeypatch.setattr(briefing, "_now", lambda: clock["t"])
    briefing.reset_briefing_cache()

    briefing.build_briefing_cached(date(2026, 6, 16), "g1", ttl=300)
    clock["t"] += 120  # < ttl
    briefing.build_briefing_cached(date(2026, 6, 16), "g2", ttl=300)

    assert state["n"] == 1  # TTL 内 → 命中
