import os
import sys
from dataclasses import dataclass
from pathlib import Path


def _resource_dir() -> Path:
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
    # Phase 2 后 config.py 位于 app/ 包内，资源 (static / templates / phase_scripts)
    # 仍在仓库根，所以向上跳一级到项目根目录。
    return Path(__file__).resolve().parent.parent


def _env_bool(name: str) -> bool:
    """读环境变量当布尔；'1'/'true'/'yes'/'on'（忽略大小写）为真。"""
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _data_dir() -> Path:
    """运行时数据目录 (stockpile.db / input / output / archive / etc).

    优先级:
    1. env LABEL_SYNC_DATA_DIR (Docker / 生产部署用, 数据走挂载卷)
    2. PyInstaller frozen exe 所在目录
    3. 代码所在目录 (开发默认; Phase 2 后 config.py 在 app/，向上一级到项目根)
    """
    env_dir = os.environ.get("LABEL_SYNC_DATA_DIR")
    if env_dir:
        return Path(env_dir).resolve()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class AppConfig:
    base_dir: Path
    resource_dir: Path
    host: str = "0.0.0.0"
    port: int = 5000
    debug: bool = False
    child_process_encoding: str = "utf-8"
    csv_fallback_encoding: str = "gbk"
    web_poll_interval_ms: int = 5000
    # 2026-05-22: 双端互传废弃 (单端线上为主), 蓝图不再注册. 代码留着, 下周确认无人用再删.
    enable_transfer: bool = False

    # CN 货 EUR 落地成本公式参数 (2026-05-23 国内同事公式):
    #   cost_eur = (shipping_rmb_per_m3 * pack_volume_m3 / unit_quantity
    #               + stock_price_rmb) / exchange_rate
    # 参数大约一年调一次, 浮动大时立即调. 浮动场景需手动改这两个常量 + 重跑 product_master importer.
    cn_shipping_rate_rmb_per_m3: float = 1000.0
    cn_exchange_rate_rmb_per_eur: float = 7.8

    # 零售价启发式: 大部分 SKU 零售价 = 批发价 × 2 (用户验证, 例外极少).
    # ERP product_data_export 只导一个 sale_price tier (批发口径 sale_money_rate_id=103),
    # 不到拉零售价 tier 的导出端点之前用这个比率派生. 26 周内零售实际成交>=3 笔的 SKU
    # 优先用 retail_revenue/retail_qty 真实均价覆盖此估算 (analytics 里实现).
    retail_to_wholesale_ratio: float = 2.0
    # 用实际观测均价覆盖 ×2 估算的最低样本数. 防止 1-2 笔异常单 (如系统 bug 价 €8.4677)
    # 错误覆盖, 但样本足够时尊重历史事实.
    retail_observed_min_qty: int = 3

    @property
    def input_dir(self) -> Path:
        return self.base_dir / "input"

    @property
    def output_dir(self) -> Path:
        return self.base_dir / "output"

    @property
    def transfer_dir(self) -> Path:
        return self.base_dir / "transfer"

    @property
    def trash_dir(self) -> Path:
        return self.base_dir / "archive"

    @property
    def templates_dir(self) -> Path:
        return self.resource_dir / "templates"

    @property
    def phase1_script(self) -> Path:
        return self.resource_dir / "phase_scripts" / "update_location_phase1.py"

    @property
    def phase2_script(self) -> Path:
        return self.resource_dir / "phase_scripts" / "update_location_phase2.py"

    @property
    def phase3_script(self) -> Path:
        return self.resource_dir / "phase_scripts" / "update_location.py"

    @property
    def temp_mapping_file(self) -> Path:
        return self.input_dir / "_temp_mapping.json"

    @property
    def temp_results_file(self) -> Path:
        return self.input_dir / "_temp_results.json"

    @property
    def stockpile_db(self) -> Path:
        return self.base_dir / "stockpile.db"


# debug 仅由 LABEL_SYNC_DEBUG 环境变量开启（本地开发热重载用）。
# 生产 Docker 不设此变量 → debug=False → waitress 正常跑，不受影响。
CONFIG = AppConfig(
    base_dir=_data_dir(),
    resource_dir=_resource_dir(),
    debug=_env_bool("LABEL_SYNC_DEBUG"),
)
