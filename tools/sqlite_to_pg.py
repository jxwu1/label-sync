"""SQLite → PostgreSQL 数据迁移脚本 (PR-B of PG migration plan).

前置条件:
    1. 目标 PG 已通过 `alembic upgrade head` 建好空 schema
    2. DATABASE_URL 环境变量或 --dsn 参数指向目标 PG
    3. --source 指向 SQLite 文件

用法:
    $env:DATABASE_URL = "postgresql+psycopg://dev:devpass@localhost:5433/label_sync"
    python tools/sqlite_to_pg.py --source ./stockpile.db

策略:
    - 按 TABLE_ORDER 依外键依赖顺序（无 FK 父表先走）迁
    - 分批写入（默认 50,000 行/批），主表 inventory_events 1.36M 行 ≈ 28 批
    - 完成后 reset_sequences() 把 PG 上 SERIAL/IDENTITY 列推到 max(id)+1
    - verify_counts() 逐表比对 SQLite vs PG，全部一致才算成功
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from collections.abc import Iterable

from sqlalchemy import MetaData, Table, create_engine, text
from sqlalchemy.orm import Session

# 迁移顺序遵守外键依赖（无 FK 父表先走，子表后走）
TABLE_ORDER: tuple[str, ...] = (
    "schema_meta",
    "import_profiles",
    "stockpile_snapshots",
    "suppliers",
    "customers",
    "foreign_customer_records",
    "stockpile",
    "stockpile_locations",  # FK → stockpile
    "stockpile_changes",
    "inventory_imports",
    "inventory_events",  # 主表 ~1.36M 行
    "backtest_runs",
    "backtest_results",  # FK → backtest_runs
)

BATCH_SIZE = 50_000


def migrate_table(sqlite_conn: sqlite3.Connection, pg_session: Session, table_name: str) -> int:
    cur = sqlite_conn.cursor()
    cur.execute(f'SELECT COUNT(*) FROM "{table_name}"')
    total = cur.fetchone()[0]
    if total == 0:
        print(f"  {table_name:32s} empty, skip")
        return 0

    cur.execute(f'SELECT * FROM "{table_name}"')
    cols = [d[0] for d in cur.description]

    meta = MetaData()
    table = Table(table_name, meta, autoload_with=pg_session.get_bind())

    inserted = 0
    batch: list[dict] = []
    for row in cur:
        batch.append(dict(zip(cols, row)))
        if len(batch) >= BATCH_SIZE:
            pg_session.execute(table.insert(), batch)
            pg_session.commit()
            inserted += len(batch)
            print(f"  {table_name:32s} {inserted:>10,}/{total:,}")
            batch = []
    if batch:
        pg_session.execute(table.insert(), batch)
        pg_session.commit()
        inserted += len(batch)
    print(f"  {table_name:32s} done ({inserted:,} rows)")
    return inserted


def reset_sequences(pg_session: Session) -> None:
    """把 SERIAL/IDENTITY 列的 sequence 推到 max(col)+1。

    SQLite 没有 sequence 概念；PG 上每个 SERIAL 列有独立 sequence，import 完后
    sequence 还停在初始 1，下次 ORM INSERT 会拿到旧的小 id 撞 PK 唯一约束。
    """
    discover_sql = text(
        """
        SELECT table_name, column_name
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND column_default LIKE 'nextval%';
        """
    )
    rows = list(pg_session.execute(discover_sql))
    for table_name, column_name in rows:
        stmt = text(
            f"""
            SELECT setval(
                pg_get_serial_sequence('"{table_name}"', '{column_name}'),
                COALESCE((SELECT MAX("{column_name}") FROM "{table_name}"), 1),
                true
            );
            """
        )
        pg_session.execute(stmt)
    pg_session.commit()
    print(f"  reset {len(rows)} sequences")


def verify_counts(
    sqlite_conn: sqlite3.Connection, pg_session: Session, tables: Iterable[str]
) -> bool:
    cur = sqlite_conn.cursor()
    all_ok = True
    print("=== verify counts ===")
    for t in tables:
        cur.execute(f'SELECT COUNT(*) FROM "{t}"')
        sqlite_n = cur.fetchone()[0]
        pg_n = pg_session.execute(text(f'SELECT COUNT(*) FROM "{t}"')).scalar()
        ok = sqlite_n == pg_n
        status = "OK" if ok else "MISMATCH"
        print(f"  {t:32s} SQLite={sqlite_n:>10,}  PG={pg_n:>10,}  {status}")
        if not ok:
            all_ok = False
    return all_ok


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", required=True, help="SQLite file path")
    ap.add_argument("--dsn", help="Override DATABASE_URL env")
    args = ap.parse_args()

    dsn = args.dsn or os.environ.get("DATABASE_URL")
    if not dsn:
        print("ERROR: 请设 DATABASE_URL env 或传 --dsn", file=sys.stderr)
        return 2
    if not dsn.startswith("postgresql"):
        print(f"ERROR: --dsn 必须是 postgresql 连接串，得到: {dsn}", file=sys.stderr)
        return 2

    print(f"source: {args.source}")
    print(f"target: {dsn.split('@')[-1] if '@' in dsn else dsn}")

    sqlite_conn = sqlite3.connect(args.source)
    pg_engine = create_engine(dsn, future=True)

    with Session(pg_engine) as session:
        # 防呆：目标 PG 必须先 alembic upgrade head（至少 schema_meta 存在）
        try:
            session.execute(text("SELECT 1 FROM schema_meta LIMIT 1"))
        except Exception as e:
            print(
                f"ERROR: 目标 PG 没找到 schema_meta 表 — 请先跑 alembic upgrade head\n  详情: {e}",
                file=sys.stderr,
            )
            return 3

        # 防呆：目标 PG 应该是空库（任何业务表有数据就拒绝）
        for t in ("inventory_events", "stockpile", "stockpile_changes"):
            n = session.execute(text(f'SELECT COUNT(*) FROM "{t}"')).scalar()
            if n and n > 0:
                print(
                    f"ERROR: 目标 PG 的 {t} 表已有 {n:,} 行数据，拒绝迁移防止双写\n"
                    f"  如需重灌请先 TRUNCATE 或 drop & alembic upgrade",
                    file=sys.stderr,
                )
                return 4

        print("=== migration ===")
        for t in TABLE_ORDER:
            migrate_table(sqlite_conn, session, t)

        print("=== reset sequences ===")
        reset_sequences(session)

        ok = verify_counts(sqlite_conn, session, TABLE_ORDER)

    sqlite_conn.close()
    return 0 if ok else 5


if __name__ == "__main__":
    sys.exit(main())
