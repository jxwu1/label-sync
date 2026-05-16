import os
from logging.config import fileConfig

from sqlalchemy import create_engine, pool

from alembic import context
from app.models import Base, get_engine

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _env_db_url() -> str | None:
    """LABEL_SYNC_DB_PATH 显式覆盖优先于 alembic.ini / models.CONFIG。

    痛点：默认 alembic.ini 写死 `sqlite:///stockpile.db`，online mode 也走
    models.get_engine() 命中 CONFIG.stockpile_db（=prod）。本地调试 / 测试期
    跑 alembic 命令会无意间改 prod schema。

    用法：
        LABEL_SYNC_DB_PATH=tmp/test.db alembic upgrade head
    """
    override = os.environ.get("LABEL_SYNC_DB_PATH")
    if override:
        return f"sqlite:///{override}"
    return None


# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = _env_db_url() or config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    override = _env_db_url()
    if override:
        connectable = create_engine(override, future=True, poolclass=pool.NullPool)
    else:
        connectable = get_engine()

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
