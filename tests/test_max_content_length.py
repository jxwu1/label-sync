"""上传体积上限契约 (codex backlog #8: 原来无 MAX_CONTENT_LENGTH).

create_app 须给 Flask 设 MAX_CONTENT_LENGTH, 给所有 request.files 上传端点
(inventory/stockpile/purchase/attendance/scan) 一个统一的体积上限,
超限由 Flask 返回 413 而非读爆内存. 默认宽松(整库 Excel 几十 MB),
可经 LABEL_SYNC_MAX_UPLOAD_MB 覆盖.
"""

from app.config import CONFIG
from server import create_app


def test_create_app_sets_max_content_length():
    app = create_app(seed_auth=False, prewarm=False)

    limit = app.config["MAX_CONTENT_LENGTH"]

    assert limit is not None
    assert limit == CONFIG.max_upload_bytes


def test_default_upload_cap_is_generous_but_bounded():
    # 默认 256MB: 远大于真实整库导出, 又给了明确上界.
    assert CONFIG.max_upload_bytes == 256 * 1024 * 1024
