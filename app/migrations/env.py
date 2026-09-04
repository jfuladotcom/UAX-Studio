from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from flask import current_app

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)

database = current_app.extensions["migrate"].db
config.set_main_option("sqlalchemy.url", str(database.engine.url).replace("%", "%%"))
target_metadata = database.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configure_args = current_app.extensions["migrate"].configure_args
    with database.engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, **configure_args)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
