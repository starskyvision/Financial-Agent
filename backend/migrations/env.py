from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from db.models import Base
target_metadata = Base.metadata


def _get_db_url() -> str:
    """Get database URL with env var priority.

    Prefers DATABASE_URL environment variable over alembic.ini value.
    Rejects the REPLACE_ME placeholder to prevent accidental use.
    """
    env_url = os.getenv("DATABASE_URL", "")
    if env_url:
        return env_url
    ini_url = config.get_main_option("sqlalchemy.url")
    if ini_url is None:
        raise RuntimeError(
            "Database URL not configured. Set DATABASE_URL env var "
            "or update sqlalchemy.url in alembic.ini."
        )
    if "REPLACE_ME" in ini_url:
        raise RuntimeError(
            "alembic.ini contains placeholder password 'REPLACE_ME'. "
            "Set DATABASE_URL environment variable instead."
        )
    return ini_url


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = _get_db_url()
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
    # Override ini URL with env var if set
    db_url = _get_db_url()
    config_section = config.get_section(config.config_ini_section, {})
    config_section["sqlalchemy.url"] = db_url
    connectable = engine_from_config(
        config_section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
