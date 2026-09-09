import os
import shutil
import subprocess
from pathlib import Path
from threading import Thread

import pytest
from werkzeug.serving import make_server

from app.extensions import db
from app.services.simple_mode import create_simple_project

BROWSER = os.environ.get("UAX_TEST_BROWSER") or shutil.which("chromium") or shutil.which("google-chrome")
if not BROWSER:
    edge = Path(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)")) / "Microsoft/Edge/Application/msedge.exe"
    BROWSER = str(edge) if edge.is_file() else None
NODE = shutil.which("node")


@pytest.mark.skipif(not BROWSER or not NODE, reason="Browser checks require Chromium/Edge and Node 22+.")
def test_responsive_brief_and_workflow_in_browser(app, tmp_path):
    with app.app_context():
        project = create_simple_project(
            name="Browser dispatch brief",
            build_type="Application",
            target_user="Dispatch coordinators",
            desired_outcome="Review delivery routes.",
            brief="Requirement: Display a route map.\nAssumption: Drivers have company phones.\nWho approves route changes?",
        )["project"]
        project.description = "Long background content " + "x" * 400
        db.session.commit()
        project_id = project.id
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = subprocess.run(
            [NODE, str(Path(__file__).parents[1] / "browser/brief_workflow.mjs"), BROWSER,
             str(tmp_path / "browser-profile"), f"http://127.0.0.1:{server.server_port}/agents/{project_id}/brief"],
            capture_output=True, text=True, timeout=100,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        print(result.stdout.strip())
    finally:
        server.shutdown()
        thread.join(timeout=5)
