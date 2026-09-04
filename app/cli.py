import click
from flask import current_app

from app.services.project_service import seed_demo_project
from app.services.schema import ensure_database_schema


def register_cli(app):
    @app.cli.command("init-db")
    def init_db():
        backup = ensure_database_schema()
        if backup:
            click.echo(f"Database backed up to {backup}.")
        click.echo("Database schema is current.")

    @app.cli.command("seed-demo")
    @click.option("--reset", is_flag=True, help="Replace the existing GalleryFlow demo.")
    def seed_demo(reset):
        seed_demo_project(reset=reset)
        click.echo("GalleryFlow demo is ready.")

    @app.cli.command("show-paths")
    def show_paths():
        click.echo(f"Data: {current_app.config['AX_DATA_DIR']}")
        click.echo(f"Uploads: {current_app.config['AX_UPLOAD_DIR']}")
        click.echo(f"Exports: {current_app.config['AX_EXPORT_DIR']}")
