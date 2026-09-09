import copy
import io
import re

import pytest

from app.extensions import db
from app.models import ActivityEvent, Project, SourceDocument, SynthesisItem, utcnow
from app.schemas import ProviderFailure
from app.services import build_instructions_service
from app.services.contract_service import list_item
from app.services.export_service import compose_export_files
from app.services.project_service import (
    brief_health,
    completion,
    create_project,
    update_project_stage,
)
from app.services.providers import DeterministicDemoProvider


@pytest.fixture()
def draft(app):
    with app.app_context():
        project = create_project(name="Background to instructions")
        db.session.commit()
        return project.id, project.active_contract.id


def add_source(client, csrf, project_id, text):
    response = client.post(
        f"/api/projects/{project_id}/sources",
        headers={"X-CSRFToken": csrf},
        json={"title": "Project notes", "text": text},
    )
    assert response.status_code == 201
    return response.get_json()["data"]["source"]["id"]


def generate(client, csrf, contract_id):
    return client.post(
        f"/api/contracts/{contract_id}/suggest", headers={"X-CSRFToken": csrf}, json={}
    )


def values(content, section, field):
    return [item["text"] for item in content[section]["fields"][field]["items"]]


def test_generate_analyzes_all_saved_background_and_preserves_uncertainty(client, app, csrf, draft, monkeypatch):
    project_id, contract_id = draft
    first = add_source(client, csrf, project_id, "Old requirement that has been replaced.")
    text = "Users: Dispatch coordinators.\nGoal: Plan tomorrow's deliveries.\nRequirement: Display a route map."
    client.patch(f"/api/sources/{first}", headers={"X-CSRFToken": csrf}, json={"edited_text": text})
    second = add_source(client, csrf, project_id, (
        "Context. " * 100
        + "\nConstraint: Work offline.\nRisk: Dispatch records may be duplicated."
        "\nAssumption: Drivers have company phones.\nIntegration: Connect to Fleet API."
        "\nData: Store vehicle and delivery records.\nWho approves route changes?"
    ))
    calls = []

    class RecordingProvider(DeterministicDemoProvider):
        def generate_structured(self, **kwargs):
            calls.append((kwargs["task_name"], kwargs["user_prompt"]))
            return super().generate_structured(**kwargs)

    monkeypatch.setattr(build_instructions_service, "get_provider", RecordingProvider)
    response = generate(client, csrf, contract_id)
    assert response.status_code == 200, response.get_json()
    content = response.get_json()["data"]["content_json"]
    assert [task for task, _ in calls] == ["intake_synthesis", "intake_synthesis", "contract_suggestions"]
    assert text in calls[-1][1]
    assert "Who approves route changes?" in calls[-1][1]
    assert "Old requirement" not in calls[-1][1]
    expected = [
        ("build_target", "core_features", "Requirement: Display a route map."),
        ("product_intent", "known_constraints", "Constraint: Work offline."),
        ("product_intent", "risks", "Risk: Dispatch records may be duplicated."),
        ("product_intent", "assumptions", "Assumption: Drivers have company phones."),
        ("build_target", "integrations", "Integration: Connect to Fleet API."),
        ("build_target", "data_entities", "Data: Store vehicle and delivery records."),
        ("definition_of_done", "open_questions", "Who approves route changes?"),
    ]
    for section, field, item in expected:
        assert item in values(content, section, field)
    assert "Dispatch coordinators" in content["product_intent"]["fields"]["target_user"]["value"]
    assert "Plan tomorrow" in content["product_intent"]["fields"]["user_goal"]["value"]
    html = client.get(f"/agents/{project_id}/instructions").get_data(as_text=True)
    assert "Assumption: Drivers have company phones." in html
    assert "Who approves route changes?" in html
    with app.app_context():
        project = db.session.get(Project, project_id)
        assert {item.source_document_id for item in project.synthesis_items} == {first, second}
        files = compose_export_files(project, utcnow())
        for _, _, item in expected:
            assert item in files["AI_BUILD_BRIEF.md"]


@pytest.mark.parametrize("blank_source", [False, True])
def test_no_background_returns_actionable_error_without_changes(client, app, csrf, draft, blank_source):
    project_id, contract_id = draft
    with app.app_context():
        project = db.session.get(Project, project_id)
        if blank_source:
            db.session.add(SourceDocument(project=project, title="Empty", source_type="pasted_text", edited_text=" \n "))
            db.session.commit()
        before = copy.deepcopy(project.active_contract.content_json)
    response = generate(client, csrf, contract_id)
    assert response.status_code == 400
    assert "Add and save Background Information" in response.get_json()["error"]["message"]
    with app.app_context():
        project = db.session.get(Project, project_id)
        assert project.active_contract.content_json == before
        assert not project.synthesis_items


@pytest.mark.parametrize("with_background", [False, True])
def test_legacy_records_remain_usable_for_generation_review_export(client, app, csrf, draft, with_background):
    project_id, contract_id = draft
    with app.app_context():
        project = db.session.get(Project, project_id)
        project.stage = "synthesis_ready"
        kept = SynthesisItem(project=project, category="assumptions", text="Legacy assumption to confirm.", inclusion_status="included")
        excluded = SynthesisItem(project=project, category="requirements", text="Excluded legacy feature.", inclusion_status="excluded")
        db.session.add_all([kept, excluded])
        content = copy.deepcopy(project.active_contract.content_json)
        content["product_intent"]["fields"]["problem_statement"]["value"] = "My carefully edited product problem."
        project.active_contract.content_json = content
        db.session.commit()
        kept_id, excluded_id = kept.id, excluded.id
        assert update_project_stage(project) == "contract_defined"
        assert len(completion(project)["checks"]) == 5
    if with_background:
        add_source(client, csrf, project_id, "Requirement: Include live delivery updates.")
    for _ in range(2):
        response = generate(client, csrf, contract_id)
        assert response.status_code == 200, response.get_json()
        content = response.get_json()["data"]["content_json"]
        assert values(content, "product_intent", "assumptions").count("Legacy assumption to confirm.") == 1
        assert "Excluded legacy feature." not in str(content)
        assert content["product_intent"]["fields"]["problem_statement"]["value"] == "My carefully edited product problem."
    with app.app_context():
        assert db.session.get(SynthesisItem, kept_id).inclusion_status == "included"
        assert db.session.get(SynthesisItem, excluded_id).inclusion_status == "excluded"
        project = db.session.get(Project, project_id)
        auto_items = [item for item in project.synthesis_items if item.source_locator == build_instructions_service.ANALYSIS_LOCATOR]
        assert len({(item.category, item.text) for item in auto_items}) == len(auto_items)
    headers = {"X-CSRFToken": csrf}
    assert client.post(f"/api/projects/{project_id}/reviews", headers=headers, json={"reviewer_type": "all"}).status_code == 200
    export = client.post(f"/api/projects/{project_id}/exports", headers=headers, json={})
    assert export.status_code == 201
    for page in ["brief", "instructions", "workflow", "quality", "export"]:
        # Quality checks retain their existing projects URL.
        path = f"/projects/{project_id}/reviews" if page == "quality" else f"/agents/{project_id}/{page}"
        assert client.get(path).status_code == 200


@pytest.mark.parametrize("failed_task", ["intake_synthesis", "contract_suggestions"])
def test_provider_fallback_uses_plain_copy_and_keeps_source_decisions(client, csrf, draft, monkeypatch, failed_task):
    project_id, contract_id = draft
    add_source(client, csrf, project_id, "Assumption: Deployment is local.\nWho owns the archive?")

    class FailingProvider(DeterministicDemoProvider):
        def generate_structured(self, **kwargs):
            if kwargs["task_name"] == failed_task:
                raise ProviderFailure("SynthesisItem validation failed: private provider detail")
            return super().generate_structured(**kwargs)

    monkeypatch.setattr(build_instructions_service, "get_provider", FailingProvider)
    response = generate(client, csrf, contract_id)
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert "built-in draft helper" in data["notice"]
    assert "synthesis" not in data["notice"].lower()
    assert "private provider detail" not in data["notice"]
    assert "Who owns the archive?" in values(data["content_json"], "definition_of_done", "open_questions")


def test_failed_generation_does_not_replace_saved_analysis(client, app, csrf, draft, monkeypatch):
    project_id, contract_id = draft
    add_source(client, csrf, project_id, "Requirement: Preserve the existing route plan.")
    assert generate(client, csrf, contract_id).status_code == 200
    with app.app_context():
        project = db.session.get(Project, project_id)
        before = copy.deepcopy(project.active_contract.content_json)
        ids = {item.id for item in project.synthesis_items}

    class InvalidDraftProvider(DeterministicDemoProvider):
        def generate_structured(self, **kwargs):
            if kwargs["task_name"] == "contract_suggestions":
                raise ValueError("Could not create a draft.")
            return super().generate_structured(**kwargs)

    monkeypatch.setattr(build_instructions_service, "get_provider", InvalidDraftProvider)
    assert generate(client, csrf, contract_id).status_code == 400
    with app.app_context():
        project = db.session.get(Project, project_id)
        assert project.active_contract.content_json == before
        assert {item.id for item in project.synthesis_items} == ids


def test_brief_order_content_visibility_and_health_states(client, app, csrf, draft):
    project_id, _ = draft
    titles = ["Original idea", "Product foundation", "Audience and user outcomes", "Core experience and features", "Data and integrations", "Constraints and risks", "Acceptance criteria"]
    for complete in [False, True]:
        if complete:
            response = client.post(f"/api/agents/{project_id}/attention/auto-correct", headers={"X-CSRFToken": csrf}, json={})
            assert response.get_json()["data"]["after_issue_count"] == 0
            with app.app_context():
                project = db.session.get(Project, project_id)
                content = copy.deepcopy(project.active_contract.content_json)
                content["build_target"]["fields"]["core_features"]["items"] = [list_item(f"Feature {i}") for i in range(10)]
                project.active_contract.content_json = content
                db.session.commit()
                assert brief_health(project)["issue_count"] == 0
        html = client.get(f"/agents/{project_id}/brief").get_data(as_text=True)
        assert "Brief health" not in html
        assert "Core brief details are present" not in html
        assert "Workflow summary" not in html
        assert "Open workflow" not in html
        assert re.findall(r'<h2 id="brief-heading-[^"]+">(.*?)</h2>', html) == titles
        assert html.index("brief-module-grid") < html.index("advanced-editing-panel")
        assert '<section class="brief-section advanced-editing-panel"' in html
        assert "<details" not in html and "<summary" not in html
        assert html.count(">Edit section</button>") == 7
        if complete:
            assert "Feature 9" in html
        for forbidden in ["create key details", "key details", "synthesis", "edit next detail", "data-focus-node-id"]:
            assert forbidden not in html.lower()
        for page in ["background", "instructions"]:
            assert f'/agents/{project_id}/{page}' in html
            response = client.get(f"/agents/{project_id}/{page}")
            assert response.status_code == 200
            assert "Generate Build Instructions" in response.get_data(as_text=True)
            assert "key details" not in response.get_data(as_text=True).lower()


def test_legacy_bookmarks_redirect_and_standalone_apis_are_retired(client, csrf, draft):
    project_id, _ = draft
    for path in [f"/projects/{project_id}/synthesis", f"/agents/{project_id}/details"]:
        response = client.get(path)
        assert response.status_code == 302
        assert response.headers["Location"].endswith(f"/agents/{project_id}/instructions")
        assert client.get(path, follow_redirects=True).status_code == 200
    headers = {"X-CSRFToken": csrf}
    assert client.post(f"/api/projects/{project_id}/synthesize", headers=headers, json={}).status_code == 404
    assert client.patch("/api/synthesis-items/retired", headers=headers, json={}).status_code == 404


def test_old_generated_copy_is_translated_without_database_migration(client, app, draft):
    project_id, _ = draft
    with app.app_context():
        project = db.session.get(Project, project_id)
        event = ActivityEvent(project=project, event_type="synthesis_generated", summary="Key details generated.")
        db.session.add(event)
        content = copy.deepcopy(project.active_contract.content_json)
        content["definition_of_done"]["fields"]["functional_acceptance_criteria"]["items"] = [list_item("Included synthesis informs contract suggestions.")]
        project.active_contract.content_json = content
        db.session.commit()
        event_id = event.id
    for path in [f"/agents/{project_id}", f"/agents/{project_id}/brief", f"/agents/{project_id}/instructions"]:
        html = client.get(path).get_data(as_text=True).lower()
        assert "key details" not in html and "synthesis" not in html
    with app.app_context():
        assert db.session.get(ActivityEvent, event_id).summary == "Key details generated."


def test_guided_creation_includes_uploaded_background(client, app, csrf):
    response = client.post("/simple/projects", data={
        "csrf_token": csrf,
        "name": "Uploaded dispatch plan",
        "brief": "Build a dispatch application.",
        "starter_document": (io.BytesIO(b"Requirement: Display vehicle maintenance history."), "fleet.txt"),
    })
    assert response.status_code == 302
    with app.app_context():
        project = Project.query.filter_by(name="Uploaded dispatch plan").one()
        assert len(project.source_documents) == 2
        assert "Requirement: Display vehicle maintenance history." in values(project.active_contract.content_json, "build_target", "core_features")
