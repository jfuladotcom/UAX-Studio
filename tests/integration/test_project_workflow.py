from app.models import ExportRecord, Finding, Project
from app.services.project_service import brief_health


def test_simple_mode_creates_agent_draft(client, app, csrf):
    assert client.get("/simple").status_code == 200

    response = client.post(
        "/simple/projects",
        data={
            "csrf_token": csrf,
            "name": "Support Triage Copilot",
            "target_user": "Support operations lead",
            "desired_outcome": "A reviewed support triage recommendation.",
            "brief": (
                "Create an agent that summarizes incoming support tickets, identifies urgency, "
                "suggests an owner, drafts a customer reply, and never sends a message without confirmation."
            ),
        },
        follow_redirects=False,
    )
    assert response.status_code == 302

    with app.app_context():
        project = Project.query.filter_by(slug="support-triage-copilot").first()
        assert project is not None
        project_id = project.id
        assert response.headers["Location"].endswith(f"/agents/{project.id}/brief")
        assert len(project.source_documents) == 1
        assert project.synthesis_items
        assert all(item.inclusion_status == "included" for item in project.synthesis_items)
        problem = project.active_contract.content_json["product_intent"]["fields"]["problem_statement"]["value"]
        assert "artist" not in problem.lower()
        assert len(project.active_workflow.nodes) >= 6
        assert len(project.active_workflow.edges) >= 7

    assert client.get(f"/projects/{project_id}/simple").status_code == 200


def test_auto_correct_attention_fills_agent_gaps(client, app, csrf):
    response = client.post(
        "/projects",
        data={"csrf_token": csrf, "name": "Empty Support Agent"},
        follow_redirects=False,
    )
    assert response.status_code == 302

    with app.app_context():
        project = Project.query.filter_by(slug="empty-support-agent").first()
        assert project is not None
        project_id = project.id
        assert brief_health(project)["issue_count"] > 0

    brief_page = client.get(f"/agents/{project_id}/brief")
    brief_html = brief_page.get_data(as_text=True)
    assert brief_page.status_code == 200
    assert "Auto correct" in brief_html
    assert f"/api/agents/{project_id}/attention/auto-correct" in brief_html
    assert "<built-in method" not in brief_html
    assert "Product foundation" in brief_html
    assert "brief-health-actions" in brief_html
    assert brief_html.index("Helpful next") < brief_html.index("brief-health-actions")

    result = client.post(
        f"/api/agents/{project_id}/attention/auto-correct",
        headers={"X-CSRFToken": csrf},
        json={},
    )
    assert result.status_code == 200, result.get_json()
    data = result.get_json()["data"]
    assert data["corrected_count"] > 0
    assert data["after_issue_count"] == 0

    with app.app_context():
        project = Project.query.filter_by(id=project_id).first()
        assert project.workflow_name == "AI agent"
        assert project.target_user
        assert project.desired_outcome
        assert project.source_documents
        assert project.active_workflow.nodes
        assert project.active_workflow.edges
        assert brief_health(project)["issue_count"] == 0


def test_primary_project_workflow(client, app, csrf):
    response = client.post(
        "/projects",
        data={
            "csrf_token": csrf,
            "name": "Support Intake Agent",
            "description": "Coordinate support triage decisions.",
            "workflow_name": "Support intake",
            "target_user": "Support lead",
            "desired_outcome": "A reviewed support triage recommendation.",
        },
        follow_redirects=False,
    )
    assert response.status_code == 302
    with app.app_context():
        project = Project.query.filter_by(slug="support-intake-agent").first()
        contract_id = project.active_contract.id
        workflow_id = project.active_workflow.id

    headers = {"X-CSRFToken": csrf}
    workflow_page = client.get(f"/projects/{project.id}/workflow")
    workflow_html = workflow_page.get_data(as_text=True)
    assert workflow_page.status_code == 200
    assert "Validate &amp; Fix" not in workflow_html
    assert 'data-active-view="graph"' in workflow_html
    assert workflow_html.index('data-workflow-view="graph"') < workflow_html.index('data-workflow-view="connections"')
    assert workflow_html.index('data-workflow-view="connections"') < workflow_html.index('data-workflow-view="sequence"')
    assert "Build Sequence" in workflow_html
    legacy_list_page = client.get(f"/projects/{project.id}/workflow?view=list")
    assert 'data-active-view="sequence"' in legacy_list_page.get_data(as_text=True)
    assert client.post(f"/api/workflows/{workflow_id}/validate", headers=headers, json={}).status_code == 404

    early_export = client.post(
        f"/api/projects/{project.id}/exports",
        headers=headers,
        json={"include_sources": False},
    )
    assert early_export.status_code == 201

    source = client.post(
        f"/api/projects/{project.id}/sources",
        headers=headers,
        json={"title": "Brief", "text": "Users need an agent to triage support requests with review checkpoints."},
    )
    assert source.status_code == 201

    assert client.post(f"/api/projects/{project.id}/synthesize", headers=headers, json={}).status_code == 200
    suggestion = client.post(f"/api/contracts/{contract_id}/suggest", headers=headers, json={})
    assert suggestion.status_code == 200, suggestion.get_json()

    start = client.post(
        f"/api/workflows/{workflow_id}/nodes",
        headers=headers,
        json={"node_type": "start", "label": "Start", "position_x": 10, "position_y": 10},
    ).get_json()["data"]["node"]
    end = client.post(
        f"/api/workflows/{workflow_id}/nodes",
        headers=headers,
        json={"node_type": "end", "label": "End", "position_x": 250, "position_y": 10},
    ).get_json()["data"]["node"]
    edge = client.post(
        f"/api/workflows/{workflow_id}/edges",
        headers=headers,
        json={
            "source_node_id": start["id"],
            "target_node_id": end["id"],
            "condition_label": "Done",
            "is_default": True,
        },
    )
    assert edge.status_code == 201
    assert client.post(
        f"/api/projects/{project.id}/reviews",
        headers=headers,
        json={"reviewer_type": "technical_feasibility_reviewer"},
    ).status_code == 200
    with app.app_context():
        finding = Finding.query.filter_by(project_id=project.id).first()

    assert client.patch(
        f"/api/findings/{finding.id}",
        headers=headers,
        json={"status": "resolved", "resolution_note": "Accepted in implementation notes."},
    ).status_code == 200

    export = client.post(
        f"/api/projects/{project.id}/exports",
        headers=headers,
        json={"include_sources": False},
    )
    assert export.status_code == 201
    with app.app_context():
        record = ExportRecord.query.filter_by(project_id=project.id).first()
    download = client.get(f"/downloads/{record.id}")
    assert download.status_code == 200
    assert download.mimetype == "application/zip"


def test_csrf_blocks_state_change(client, app):
    with app.app_context():
        project = Project.query.filter_by(slug="galleryflow-artist-submission-coordination").first()
    response = client.post(f"/api/projects/{project.id}/synthesize", json={})
    assert response.status_code == 400
