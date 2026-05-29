"""把线上 PostgreSQL 整库拉到本地 PG（单向覆盖本地）。

为什么要它：本地空库 → 标签流程跑不出异常、复现不了业务 bug，逼得只能上线上测。
灌一份线上真实数据到本地后，同样的 bug 本地就能复现，服务器彻底退出调试内循环。

只做"线上 → 本地"覆盖，符合项目约定（两端绝不合并、只允许整库替换）。**绝不写线上。**

前置条件:
  1. 本机装了 PG 客户端工具 pg_dump / pg_restore（大版本与线上一致，PG17）。
     Windows: winget install PostgreSQL.PostgreSQL.17（或只装 client）。
  2. 能连到线上 PG。线上仅内网可达，通常需要其一：
       - 处于公司网络内；或
       - SSH 隧道到 Hetzner：
           ssh -L 5544:<coolify-pg-容器host>:5432 <user>@<hetzner-ip>
         然后 PROD_DATABASE_URL 指向 localhost:5544
  3. 凭据在 1Password「Servers」vault。

用法 (PowerShell):
  $env:PROD_DATABASE_URL = "postgresql://<user>:<pass>@<host>:<port>/<db>"   # 线上（只读取）
  $env:DATABASE_URL      = "postgresql+psycopg://dev:devpass@localhost:5433/label_sync"  # 本地目标
  python tools/pull_prod_db.py

安全闸:
  - 本地目标 host 必须是 localhost / 127.0.0.1，否则拒绝执行（防误覆盖远端库）。
  - 仅对 PROD_DATABASE_URL 执行 pg_dump（只读），写操作只落本地。
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit


def _to_libpq(url: str) -> str:
    """SQLAlchemy 风格 (postgresql+psycopg://) → libpq 能用的 postgresql://。"""
    return url.replace("postgresql+psycopg://", "postgresql://", 1).replace(
        "postgresql+psycopg2://", "postgresql://", 1
    )


def _require(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        sys.exit(f"✗ 缺少环境变量 {name}（见本文件顶部用法说明）")
    return val


def _assert_local(local_url: str) -> None:
    host = (urlsplit(_to_libpq(local_url)).hostname or "").lower()
    if host not in {"localhost", "127.0.0.1"}:
        sys.exit(
            f"✗ 安全闸：本地目标 DATABASE_URL 的 host 是 {host!r}，不是 localhost。"
            f"\n  为防误覆盖远端库，本脚本只允许覆盖本地 PG。"
        )


def _run(cmd: list[str]) -> None:
    printable = " ".join(c if "://" not in c else "<redacted-dsn>" for c in cmd)
    print(f"$ {printable}")
    subprocess.run(cmd, check=True)


def main() -> None:
    prod = _to_libpq(_require("PROD_DATABASE_URL"))
    local = _to_libpq(_require("DATABASE_URL"))
    _assert_local(local)

    print("⚠ 即将用线上数据【整库覆盖】本地 PG，本地现有数据会被清掉。")
    print(f"  线上(只读): {urlsplit(prod).hostname}:{urlsplit(prod).port or 5432}")
    print(f"  本地(覆盖): {urlsplit(local).hostname}:{urlsplit(local).port or 5432}")

    with tempfile.TemporaryDirectory() as tmp:
        dump = str(Path(tmp) / "prod.dump")
        # custom format，便于 pg_restore --clean
        _run(["pg_dump", "--format=custom", "--no-owner", "--no-privileges",
              "--file", dump, prod])
        # --clean --if-exists：先删本地同名对象再灌，得到与线上一致的镜像
        _run(["pg_restore", "--clean", "--if-exists", "--no-owner",
              "--no-privileges", "--dbname", local, dump])

    print("\n✓ 本地 PG 已替换为线上数据快照。`./dev.ps1` 起服务即可用真实数据复现/调试。")


if __name__ == "__main__":
    main()
