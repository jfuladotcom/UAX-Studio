import copy
import re

import pytest

from app.extensions import db
from app.models import ExperienceContract, Project, SourceDocument, SynthesisItem, utcnow
from app.services.brief_service import BRIEF_MODULES
from app.services.contract_service import list_item
from app.services.export_service import compose_export_files
from app.services.project_service import create_project
from app.services.review_service import _review_context
from app.services.workflow_service import serialize_workflow


@pytest.fixture()
def editable(app):
    with app.app_context():
        project = create_project(name="Editable dispatch agent", description="Original dispatch idea.",
                                 workflow_name="Dispatch application", target_user="Coordinators", desired_outcome="Plan routes.")
        content = copy.deepcopy(project.active_contract.content_json)
        content["build_target"]["fields"]["core_features"]["items"] = [list_item("Old route feature")]
        project.active_contract.content_json = content
        db.session.commit()
        return project.id


def read_section(client, project_id, key):
    response = client.get(f"/api/agents/{project_id}/brief/sections/{key}")
    assert response.status_code == 200
    return response.get_json()["data"]["module"]


def save_section(client, csrf, project_id, key, changes, revision=None):
    revision = revision or read_section(client, project_id, key)["revision"]
    return client.patch(f"/api/agents/{project_id}/brief/sections/{key}",
                        headers={"X-CSRFToken": csrf}, json={"fields": changes, "revision": revision})


def test_open_agent_links_land_on_overview_with_active_navigation(client, editable):
    # Visiting another tab must not change where the dashboard opens this agent.
    for suffix in ["brief", "workflow", "export"]:
        assert client.get(f"/agents/{editable}/{suffix}").status_code == 200
    html = client.get("/agents").get_data(as_text=True)
    links = re.findall(r'<a class="button primary" href="([^"]+)">Open agent</a>', html)
    assert f"/agents/{editable}" in links
    for href in links:
        page = client.get(href)
        assert page.status_code == 200
        active = re.search(r'<a class="active" href="([^"]+)"\s+aria-current="page">\s*<span class="app-rail-label">([^<]+)', page.get_data(as_text=True))
        assert active and active.group(2) == "Overview"


@pytest.mark.parametrize("key", BRIEF_MODULES)
def test_every_module_loads_only_its_canonical_fields_and_saves(client, app, csrf, editable, key):
    module = read_section(client, editable, key)
    title, keys = BRIEF_MODULES[key]
    assert module["title"] == title
    assert [field["key"] for field in module["fields"]] == keys
    with app.app_context():
        project = db.session.get(Project, editable)
        before = copy.deepcopy(project.active_contract.content_json)
        workflow_before = serialize_workflow(project.active_workflow)
        counts = [model.query.count() for model in [Project, ExperienceContract, SourceDocument, SynthesisItem]]
    changes = {}
    for field in module["fields"]:
        changes[field["key"]] = f"Edited {field['label']}" if field["type"] == "text" else [{"text": f"Edited {field['label']}"}]
    response = save_section(client, csrf, editable, key, changes, module["revision"])
    assert response.status_code == 200, response.get_json()
    assert "Changes saved" in response.get_json()["message"]
    assert 'data-edit-section=' in response.get_json()["data"]["modules_html"]
    after = read_section(client, editable, key)
    for field in after["fields"]:
        assert (field["value"] if field["type"] == "text" else field["items"][0]["text"]) == f"Edited {field['label']}"
    with app.app_context():
        project = db.session.get(Project, editable)
        assert counts == [model.query.count() for model in [Project, ExperienceContract, SourceDocument, SynthesisItem]]
        assert workflow_before == serialize_workflow(project.active_workflow)
        for section, value in before.items():
            for name, field in value["fields"].items():
                if f"{section}.{name}" not in changes:
                    assert project.active_contract.content_json[section]["fields"][name] == field
        exported = compose_export_files(project, utcnow())
        review_context = _review_context(project)
        for field in after["fields"]:
            text = f"Edited {field['label']}"
            assert text in review_context
            assert any(text in file for file in exported.values())
    assert client.get(f"/agents/{editable}/brief").status_code == 200
    assert client.get(f"/agents/{editable}/instructions").status_code == 200


def test_shared_values_use_existing_fields_across_modules_and_instructions(client, app, csrf, editable):
    response = save_section(client, csrf, editable, "original_idea", {
        "project.description": "Revised starting idea.",
        "build_target.artifact_type": "Delivery portal",
        "product_intent.target_user": "Regional dispatchers",
        "product_intent.desired_outcome": "Approve tomorrow's routes.",
    })
    assert response.status_code == 200
    for key in ["original_idea", "product_foundation", "audience"]:
        fields = {field["key"]: field for field in read_section(client, editable, key)["fields"]}
        assert fields["product_intent.desired_outcome"]["value"] == "Approve tomorrow's routes."
    with app.app_context():
        project = db.session.get(Project, editable)
        assert project.workflow_name == "Delivery portal"
        assert project.target_user == "Regional dispatchers"
        assert project.description == "Revised starting idea."
        assert project.active_contract.content_json["product_intent"]["fields"]["target_user"]["value"] == "Regional dispatchers"
        content = copy.deepcopy(project.active_contract.content_json)
        contract_id = project.active_contract.id
        content["product_intent"]["fields"]["target_user"]["value"] = "Edited in full instructions"
    assert client.patch(f"/api/contracts/{contract_id}", headers={"X-CSRFToken": csrf}, json={"content_json": content}).status_code == 200
    fields = read_section(client, editable, "audience")["fields"]
    assert fields[0]["value"] == "Edited in full instructions"


def test_repeated_list_saves_preserve_ids_and_do_not_duplicate_items(client, csrf, editable):
    module = read_section(client, editable, "core_experience")
    field = module["fields"][0]
    original_id = field["items"][0]["id"]
    items = [{"id": original_id, "text": "Revised feature"}, {"text": "Additional feature"}]
    assert save_section(client, csrf, editable, "core_experience", {field["key"]: items}).status_code == 200
    saved = read_section(client, editable, "core_experience")["fields"][0]["items"]
    assert saved[0]["id"] == original_id
    assert save_section(client, csrf, editable, "core_experience", {field["key"]: [{"id": item["id"], "text": item["text"]} for item in saved]}).status_code == 200
    assert read_section(client, editable, "core_experience")["fields"][0]["items"] == saved
    assert save_section(client, csrf, editable, "core_experience", {field["key"]: []}).status_code == 200
    assert not read_section(client, editable, "core_experience")["fields"][0]["items"]


def test_validation_conflicts_and_csrf_leave_saved_data_intact(client, app, csrf, editable):
    module = read_section(client, editable, "original_idea")
    assert save_section(client, csrf, editable, "original_idea", {"project.description": "Saved elsewhere"}).status_code == 200
    conflict = save_section(client, csrf, editable, "original_idea", {"project.description": "Stale overwrite"}, module["revision"])
    assert conflict.status_code == 409
    assert "changed since you opened" in conflict.get_json()["error"]["message"]
    for changes in [
        {"project.description": "Must roll back", "product_intent.target_user": ["invalid"]},
        {"project.description": "Must roll back", "workflow.nodes": []},
        {"product_intent.target_user": "x" * 241},
    ]:
        assert save_section(client, csrf, editable, "original_idea", changes).status_code == 400
    assert client.patch(f"/api/agents/{editable}/brief/sections/original_idea", json={}).status_code == 400
    assert client.get(f"/api/agents/{editable}/brief/sections/unrelated").status_code == 404
    with app.app_context():
        assert db.session.get(Project, editable).description == "Saved elsewhere"
