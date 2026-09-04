from __future__ import annotations

import copy
from pathlib import Path

from flask import current_app

from app.extensions import db
from app.models import (
    ActivityEvent,
    ExperienceContract,
    Finding,
    Project,
    ReviewRun,
    SourceDocument,
    SynthesisItem,
    Workflow,
    WorkflowEdge,
    WorkflowNode,
    utcnow,
)
from app.schemas import ContractSuggestion, SynthesisResult, dump_model
from app.services.contract_service import blank_contract_content, ensure_contract_shape, list_item
from app.services.prompt_service import get_prompt
from app.services.providers import DeterministicDemoProvider
from app.services.security import remove_tree_safely, slugify

STAGES = [
    "draft",
    "sources_ready",
    "synthesis_ready",
    "contract_defined",
    "workflow_ready",
    "reviewed",
    "export_ready",
]


def create_project(
    *,
    name: str,
    description: str = "",
    workflow_name: str = "",
    target_user: str = "",
    desired_outcome: str = "",
) -> Project:
    base_slug = slugify(name)
    slug = base_slug
    counter = 2
    while Project.query.filter_by(slug=slug).first():
        slug = f"{base_slug}-{counter}"
        counter += 1
    project = Project(
        name=name.strip() or "Untitled project",
        slug=slug,
        description=description.strip(),
        workflow_name=workflow_name.strip() or "Build plan",
        target_user=target_user.strip(),
        desired_outcome=desired_outcome.strip(),
    )
    db.session.add(project)
    db.session.flush()
    db.session.add(
        ExperienceContract(project=project, version_number=1, content_json=blank_contract_content())
    )
    db.session.add(
        Workflow(
            project=project,
            name=project.workflow_name or "Build plan",
            version_number=1,
            viewport_json={"zoom": 1, "pan_x": 0, "pan_y": 0},
        )
    )
    record_activity(project, "project_created", "Build brief created.")
    update_project_stage(project)
    return project


def record_activity(project: Project, event_type: str, summary: str, metadata: dict | None = None) -> None:
    db.session.add(
        ActivityEvent(
            project=project,
            event_type=event_type,
            summary=summary[:260],
            metadata_json=metadata or {},
        )
    )


def update_project_stage(project: Project) -> str:
    stage = "draft"
    if project.source_documents:
        stage = "sources_ready"
    if any(item.inclusion_status == "included" for item in project.synthesis_items):
        stage = "synthesis_ready"
    contract = project.active_contract
    if contract and _contract_has_content(contract):
        stage = "contract_defined"
    workflow = project.active_workflow
    if workflow and workflow.nodes and workflow.edges:
        stage = "workflow_ready"
    if project.review_runs:
        stage = "reviewed"
    if project.exports:
        stage = "export_ready"
    project.stage = stage
    project.updated_at = utcnow()
    return stage


def completion(project: Project) -> dict:
    checks = [
        ("Idea or background added", bool(project.source_documents)),
        ("Key details ready", any(item.inclusion_status == "included" for item in project.synthesis_items)),
        ("Build instructions drafted", bool(project.active_contract and _contract_has_content(project.active_contract))),
        (
            "Step map connected",
            bool(
                project.active_workflow
                and project.active_workflow.nodes
                and project.active_workflow.edges
            ),
        ),
        ("Quality check run", bool(project.review_runs)),
        ("Export package created", bool(project.exports)),
    ]
    done = sum(1 for _, value in checks if value)
    return {
        "checks": checks,
        "percent": round(done / len(checks) * 100),
        "next_action": next((label for label, value in checks if not value), "Export the AI build brief"),
    }


def brief_health(project: Project) -> dict:
    contract = ensure_contract_shape(project.active_contract.content_json if project.active_contract else {})
    workflow = project.active_workflow
    core_features = _unique_values(
        _contract_list_values(contract, "build_target", "core_features")
        + _contract_list_values(contract, "definition_of_done", "functional_acceptance_criteria")
        + _synthesis_texts(project, "requirements")
        + _synthesis_texts(project, "tasks")
    )
    surfaces = _unique_values(
        _contract_list_values(contract, "build_target", "primary_surfaces")
        + _contract_list_values(contract, "implementation_plan", "routes_or_views")
    )
    data_items = _unique_values(
        _contract_list_values(contract, "build_target", "data_entities")
        + _contract_list_values(contract, "data_and_memory", "may_read")
        + _contract_list_values(contract, "data_and_memory", "may_create_or_modify")
    )
    acceptance = _unique_values(
        _contract_list_values(contract, "implementation_plan", "acceptance_tests")
        + _contract_list_values(contract, "definition_of_done", "functional_acceptance_criteria")
        + _contract_list_values(contract, "definition_of_done", "ux_acceptance_criteria")
    )

    checks = [
        _health_check("product_type", "Product type", _project_type(project, contract)),
        _health_check("audience", "Primary audience", project.target_user or _contract_text(contract, "product_intent", "target_user")),
        _health_check("outcome", "Desired outcome", project.desired_outcome or _contract_text(contract, "product_intent", "desired_outcome")),
        _health_check("features", "Core features", core_features),
        _health_check("surfaces", "Screens or pages", surfaces),
        _health_check("acceptance", "Acceptance criteria", acceptance),
    ]
    advisory_checks = [
        _health_check("source", "Source context", project.source_documents),
        _health_check("data", "Data model or content", data_items),
        _health_check("workflow", "Workflow steps", workflow.nodes if workflow and workflow.nodes and workflow.edges else []),
    ]
    required_issues = [
        {
            "key": check["key"],
            "title": check["label"],
            "detail": f"Add {check['label'].lower()} before relying on the brief.",
        }
        for check in checks
        if not check["complete"]
    ]
    advisory_issues = [
        {
            "key": check["key"],
            "title": check["label"],
            "detail": f"Consider adding {check['label'].lower()} for a stronger handoff.",
        }
        for check in advisory_checks
        if not check["complete"]
    ]
    workflow_detail_node = next(
        (
            node
            for node in (workflow.nodes if workflow and workflow.nodes and workflow.edges else [])
            if _workflow_node_needs_detail(node)
        ),
        None,
    )
    if workflow_detail_node:
        advisory_issues.append(
            {
                "key": "workflow_detail",
                "title": "Workflow step details",
                "detail": f"Complete details for {workflow_detail_node.label}.",
            }
        )
    open_findings = [finding for finding in project.findings if finding.status == "open"]
    advisory_issues.extend(
        {
            "key": f"finding-{finding.id}",
            "title": finding.title,
            "detail": f"{finding.severity.title()} quality note: {finding.recommendation}",
        }
        for finding in open_findings
    )
    total = len(checks) + len(advisory_checks)
    done = sum(1 for check in checks + advisory_checks if check["complete"])
    percent = round(done / total * 100) if total else 0

    if project.exports:
        status_key = "exported"
        status_label = "Exported"
        summary = "A build package has been created."
    elif required_issues:
        status_key = "needs_input"
        status_label = "Needs attention"
        summary = f"{len(required_issues)} required item{'s' if len(required_issues) != 1 else ''} need attention."
    elif advisory_issues:
        status_key = "needs_review"
        status_label = "Needs review"
        summary = f"{len(advisory_issues)} item{'s' if len(advisory_issues) != 1 else ''} could improve the handoff."
    else:
        status_key = "ready_to_export"
        status_label = "Ready to export"
        summary = "Core brief details are present."

    return {
        "status_key": status_key,
        "status_label": status_label,
        "summary": summary,
        "percent": percent,
        "required_checks": checks,
        "advisory_checks": advisory_checks,
        "required_issues": required_issues,
        "advisory_issues": advisory_issues,
        "issue_count": len(required_issues) + len(advisory_issues),
        "required_count": len(required_issues),
        "advisory_count": len(advisory_issues),
    }


def brief_review_sections(project: Project) -> list[dict]:
    contract = ensure_contract_shape(project.active_contract.content_json if project.active_contract else {})
    return [
        {
            "title": "Product foundation",
            "edit_target": "contract",
            "decisions": [
                _decision("Project type", _project_type(project, contract), "from_input" if project.workflow_name and project.workflow_name != "Build plan" else _field_state(contract, "build_target", "artifact_type")),
                _decision("Problem statement", _contract_text(contract, "product_intent", "problem_statement"), _field_state(contract, "product_intent", "problem_statement")),
                _decision("Desired outcome", project.desired_outcome or _contract_text(contract, "product_intent", "desired_outcome"), "from_input" if project.desired_outcome else _field_state(contract, "product_intent", "desired_outcome")),
            ],
        },
        {
            "title": "Audience and user outcomes",
            "edit_target": "contract",
            "decisions": [
                _decision("Primary audience", project.target_user or _contract_text(contract, "product_intent", "target_user"), "from_input" if project.target_user else _field_state(contract, "product_intent", "target_user")),
                _decision("User goal", _contract_text(contract, "product_intent", "user_goal"), _field_state(contract, "product_intent", "user_goal")),
                _decision("Success measures", _contract_list_values(contract, "product_intent", "success_measures"), _field_state(contract, "product_intent", "success_measures")),
            ],
        },
        {
            "title": "Core experience and features",
            "edit_target": "contract",
            "decisions": [
                _decision("Core features", _contract_list_values(contract, "build_target", "core_features") or _synthesis_texts(project, "requirements"), _field_state(contract, "build_target", "core_features")),
                _decision("Screens, pages, or surfaces", _contract_list_values(contract, "build_target", "primary_surfaces"), _field_state(contract, "build_target", "primary_surfaces")),
                _decision("Implementation steps", _contract_list_values(contract, "implementation_plan", "implementation_steps"), _field_state(contract, "implementation_plan", "implementation_steps")),
            ],
        },
        {
            "title": "Data and integrations",
            "edit_target": "contract",
            "decisions": [
                _decision("Data models or content", _contract_list_values(contract, "build_target", "data_entities"), _field_state(contract, "build_target", "data_entities")),
                _decision("Integrations", _contract_list_values(contract, "build_target", "integrations"), _field_state(contract, "build_target", "integrations")),
                _decision("Permissions and roles", _contract_list_values(contract, "build_target", "auth_and_roles"), _field_state(contract, "build_target", "auth_and_roles")),
            ],
        },
        {
            "title": "Constraints and risks",
            "edit_target": "contract",
            "decisions": [
                _decision("Known constraints", _contract_list_values(contract, "product_intent", "known_constraints"), _field_state(contract, "product_intent", "known_constraints")),
                _decision("Out of scope", _contract_list_values(contract, "implementation_plan", "out_of_scope"), _field_state(contract, "implementation_plan", "out_of_scope")),
                _decision("Open questions", _contract_list_values(contract, "definition_of_done", "open_questions"), _field_state(contract, "definition_of_done", "open_questions")),
            ],
        },
        {
            "title": "Acceptance criteria",
            "edit_target": "contract",
            "decisions": [
                _decision("Functional acceptance", _contract_list_values(contract, "definition_of_done", "functional_acceptance_criteria"), _field_state(contract, "definition_of_done", "functional_acceptance_criteria")),
                _decision("UX acceptance", _contract_list_values(contract, "definition_of_done", "ux_acceptance_criteria"), _field_state(contract, "definition_of_done", "ux_acceptance_criteria")),
                _decision("Builder instructions", _contract_text(contract, "implementation_plan", "ai_builder_instructions"), _field_state(contract, "implementation_plan", "ai_builder_instructions")),
            ],
        },
    ]


def workflow_attention_node(project: Project) -> WorkflowNode | None:
    workflow = project.active_workflow
    if not workflow or not workflow.nodes:
        return None

    node_ids = {node.id for node in workflow.nodes}
    finding_node = _finding_attention_node(project, node_ids)
    if finding_node:
        return finding_node

    incomplete = next((node for node in workflow.nodes if _workflow_node_needs_detail(node)), None)
    if incomplete:
        return incomplete

    health = brief_health(project)
    if health["required_issues"] or health["advisory_issues"]:
        return max(workflow.nodes, key=_workflow_attention_score)
    return workflow.nodes[0]


def auto_correct_attention(project: Project) -> dict:
    before = brief_health(project)
    corrections = []
    contract_record = project.active_contract
    if not contract_record:
        contract_record = ExperienceContract(
            project=project,
            version_number=(project.contracts[-1].version_number if project.contracts else 0) + 1,
            content_json=blank_contract_content("system_seeded"),
        )
        db.session.add(contract_record)
        db.session.flush()

    contract = ensure_contract_shape(contract_record.content_json)
    contract_changed = False
    issues = before["required_issues"] + before["advisory_issues"]

    for issue in issues:
        changed, message, changed_contract = _auto_correct_issue(project, contract, issue["key"])
        if not changed:
            continue
        corrections.append({"key": issue["key"], "title": issue["title"], "message": message})
        contract_changed = contract_changed or changed_contract

    if contract_changed:
        contract_record.content_json = contract
        contract_record.updated_at = utcnow()

    update_project_stage(project)
    db.session.flush()
    after = brief_health(project)
    if corrections:
        record_activity(
            project,
            "attention_auto_corrected",
            f"Auto correct updated {len(corrections)} attention item{'s' if len(corrections) != 1 else ''}.",
            {
                "corrected": [correction["key"] for correction in corrections],
                "before_issue_count": before["issue_count"],
                "after_issue_count": after["issue_count"],
            },
        )

    return {
        "corrected_count": len(corrections),
        "corrections": corrections,
        "before_issue_count": before["issue_count"],
        "after_issue_count": after["issue_count"],
        "health": after,
    }


def _auto_correct_issue(project: Project, contract: dict, key: str) -> tuple[bool, str, bool]:
    if key == "product_type":
        return _auto_correct_product_type(project, contract)
    if key == "audience":
        return _auto_correct_audience(project, contract)
    if key == "outcome":
        return _auto_correct_outcome(project, contract)
    if key == "features":
        return _auto_correct_features(project, contract)
    if key == "surfaces":
        return _auto_correct_surfaces(project, contract)
    if key == "acceptance":
        return _auto_correct_acceptance(project, contract)
    if key == "source":
        return _auto_correct_source_context(project)
    if key == "data":
        return _auto_correct_data(project, contract)
    if key == "workflow":
        return _auto_correct_workflow(project)
    if key == "workflow_detail":
        return _auto_correct_workflow_detail(project)
    if key.startswith("finding-"):
        return _auto_correct_finding(project, contract, key.removeprefix("finding-"))
    return False, "", False


def _auto_correct_product_type(project: Project, contract: dict) -> tuple[bool, str, bool]:
    current = _project_type(project, contract)
    value = current or _infer_attention_artifact_type(_attention_context(project))
    changed = False
    if (not project.workflow_name or project.workflow_name == "Build plan") and value:
        project.workflow_name = value[:160]
        changed = True
        if project.active_workflow and project.active_workflow.name == "Build plan":
            project.active_workflow.name = project.workflow_name
    contract_changed = _set_contract_text_if_blank(contract, "build_target", "artifact_type", value)
    return changed or contract_changed, f"Product type set to {value}.", contract_changed


def _auto_correct_audience(project: Project, contract: dict) -> tuple[bool, str, bool]:
    value = (
        project.target_user
        or _contract_text(contract, "product_intent", "target_user")
        or _first_synthesis_text(project, ["users"])
        or "Primary user or operator"
    )
    changed = False
    if not project.target_user and value:
        project.target_user = value[:240]
        changed = True
    contract_changed = _set_contract_text_if_blank(contract, "product_intent", "target_user", value)
    return changed or contract_changed, "Primary audience filled from the available agent context.", contract_changed


def _auto_correct_outcome(project: Project, contract: dict) -> tuple[bool, str, bool]:
    value = (
        project.desired_outcome
        or _contract_text(contract, "product_intent", "desired_outcome")
        or _first_synthesis_text(project, ["goals"])
        or f"A clear, usable {(_subject_label(project) or 'agent')} that reaches the intended result."
    )
    changed = False
    if not project.desired_outcome and value:
        project.desired_outcome = value
        changed = True
    contract_changed = _set_contract_text_if_blank(contract, "product_intent", "desired_outcome", value)
    return changed or contract_changed, "Desired outcome filled from the available agent context.", contract_changed


def _auto_correct_features(project: Project, contract: dict) -> tuple[bool, str, bool]:
    values = _first_nonempty_values(
        _synthesis_texts(project, "requirements") + _synthesis_texts(project, "tasks"),
        [
            f"Capture the core request for {_subject_label(project)}.",
            "Support the primary user flow from start through final output.",
            "Prepare an exportable handoff for the builder.",
        ],
    )
    contract_changed = _append_contract_items(contract, "build_target", "core_features", values[:4])
    return contract_changed, "Core features added to the agent instructions.", contract_changed


def _auto_correct_surfaces(project: Project, contract: dict) -> tuple[bool, str, bool]:
    values = [
        "Primary workspace or entry screen",
        "Detail or editing view",
        "Output, review, or handoff view",
    ]
    changed = _append_contract_items(contract, "build_target", "primary_surfaces", values)
    changed = _append_contract_items(contract, "implementation_plan", "routes_or_views", values) or changed
    return changed, "Screens or pages added to the agent instructions.", changed


def _auto_correct_acceptance(project: Project, contract: dict) -> tuple[bool, str, bool]:
    values = [
        "The main user flow reaches the desired outcome.",
        "Missing information shows a clear next action.",
        "The handoff includes the brief, workflow, data, and acceptance criteria.",
    ]
    changed = _append_contract_items(contract, "definition_of_done", "functional_acceptance_criteria", values)
    changed = _append_contract_items(contract, "implementation_plan", "acceptance_tests", values) or changed
    return changed, "Acceptance criteria added to the agent instructions.", changed


def _auto_correct_source_context(project: Project) -> tuple[bool, str, bool]:
    if project.source_documents:
        return False, "", False
    text = _source_text_from_project(project)
    db.session.add(
        SourceDocument(
            project=project,
            title="Agent summary",
            description="Auto correct created this from the saved agent details.",
            source_type="agent_summary",
            original_filename="",
            stored_filename="",
            mime_type="text/plain",
            file_size=len(text.encode("utf-8")),
            extracted_text=text,
            edited_text=text,
            extraction_status="ready",
        )
    )
    return True, "Source context saved from the agent summary.", False


def _auto_correct_data(project: Project, contract: dict) -> tuple[bool, str, bool]:
    values = [
        "Agent brief",
        "Workflow step",
        "Reviewed output",
    ]
    changed = _append_contract_items(contract, "build_target", "data_entities", values)
    changed = _append_contract_items(contract, "data_and_memory", "may_read", ["Agent brief and saved background info"]) or changed
    changed = _append_contract_items(contract, "data_and_memory", "may_create_or_modify", values[1:]) or changed
    return changed, "Data model details added to the agent instructions.", changed


def _auto_correct_workflow(project: Project) -> tuple[bool, str, bool]:
    workflow = project.active_workflow
    if not workflow:
        workflow = Workflow(
            project=project,
            name=project.workflow_name or "Agent workflow",
            version_number=(project.workflows[-1].version_number if project.workflows else 0) + 1,
            viewport_json={"zoom": 0.92, "pan_x": 20, "pan_y": 20},
        )
        db.session.add(workflow)
        db.session.flush()

    if workflow.nodes and workflow.edges:
        return False, "", False

    if not workflow.nodes:
        _seed_attention_workflow(project, workflow)
        return True, "Starter workflow steps added.", False

    nodes = list(workflow.nodes)
    if len(nodes) == 1:
        end = _attention_workflow_node(
            workflow,
            "end",
            "Agent output ready",
            nodes[0].position_x + 280,
            nodes[0].position_y,
            "System",
            "The agent has enough structured detail to prepare the final handoff.",
            "Agent output is ready.",
        )
        db.session.flush()
        _attention_workflow_edge(workflow, nodes[0], end, "Next", 1, True)
        workflow.status = "ready"
        workflow.viewport_json = {"zoom": 0.92, "pan_x": 20, "pan_y": 20}
        return True, "Workflow endpoint and connection added.", False

    for index, (source, target) in enumerate(zip(nodes, nodes[1:], strict=False), start=1):
        _attention_workflow_edge(workflow, source, target, "Next", index, index == 1)
    workflow.status = "ready"
    workflow.viewport_json = {"zoom": 0.92, "pan_x": 20, "pan_y": 20}
    return True, "Existing workflow steps connected.", False


def _auto_correct_workflow_detail(project: Project) -> tuple[bool, str, bool]:
    workflow = project.active_workflow
    if not workflow:
        return False, "", False
    node = next((candidate for candidate in workflow.nodes if _workflow_node_needs_detail(candidate)), None)
    if not node:
        return False, "", False

    changed = False
    subject = _subject_label(project)
    if not node.label.strip():
        node.label = node.node_type.replace("_", " ").title()
        changed = True
    if not node.actor.strip():
        node.actor = _default_actor_for_node_type(node.node_type)
        changed = True
    if not node.description.strip():
        node.description = f"Handle the {node.label.lower()} step for {subject}."
        changed = True

    config = dict(node.configuration_json or {})
    defaults = {
        "expected_input": "Current agent brief context",
        "expected_output": f"Updated {subject} details",
        "data_accessed": "Agent brief, workflow steps, and saved background info",
        "permission_level": "review",
        "confidence_behavior": "Continue when the next step is clear; ask for help when important details are missing.",
        "user_visible_status": f"{node.label} is in progress.",
        "recovery_behavior": "Keep previous values available and route unclear details back to the user.",
    }
    for field, value in defaults.items():
        if not str(config.get(field, "")).strip():
            config[field] = value
            changed = True

    if changed:
        node.configuration_json = config
        node.updated_at = utcnow()
    return changed, f"Workflow details completed for {node.label}.", False


def _auto_correct_finding(project: Project, contract: dict, finding_id: str) -> tuple[bool, str, bool]:
    finding = next(
        (candidate for candidate in project.findings if candidate.id == finding_id and candidate.status == "open"),
        None,
    )
    if not finding:
        return False, "", False

    recommendation = finding.recommendation.strip() or finding.title
    contract_changed = _add_finding_recommendation(contract, finding.related_contract_section, recommendation)
    node_changed = _add_finding_recommendation_to_node(finding, recommendation)
    finding.status = "resolved"
    finding.resolution_note = "Auto correct added this recommendation to the agent instructions."
    finding.updated_at = utcnow()
    return True, f"Quality note handled: {finding.title}", contract_changed or node_changed


def _add_finding_recommendation(contract: dict, section_key: str, recommendation: str) -> bool:
    if not recommendation:
        return False
    target = section_key if section_key in contract else ""
    if target == "autonomy_controls":
        return _append_contract_items(contract, "autonomy_controls", "confirmation_actions", [recommendation])
    if target == "build_target":
        return _append_contract_items(contract, "build_target", "nonfunctional_requirements", [recommendation])
    if target == "implementation_plan":
        return _append_contract_items(contract, "implementation_plan", "acceptance_tests", [recommendation])
    if target == "responsibility_model":
        return _append_contract_items(contract, "responsibility_model", "human_responsibilities", [recommendation])
    return _append_contract_items(contract, "definition_of_done", "functional_acceptance_criteria", [recommendation])


def _add_finding_recommendation_to_node(finding: Finding, recommendation: str) -> bool:
    if not finding.related_workflow_node_id or not recommendation:
        return False
    node = db.session.get(WorkflowNode, finding.related_workflow_node_id)
    if not node:
        return False
    config = dict(node.configuration_json or {})
    current = str(config.get("recovery_behavior", "")).strip()
    if recommendation.lower() in current.lower():
        return False
    config["recovery_behavior"] = f"{current}\n{recommendation}".strip()
    node.configuration_json = config
    node.updated_at = utcnow()
    return True


def _set_contract_text_if_blank(contract: dict, section_key: str, field_key: str, value: str) -> bool:
    field = contract.get(section_key, {}).get("fields", {}).get(field_key)
    if not field or field.get("type") != "text":
        return False
    clean = _compact_text(value, 2000)
    if not clean or field.get("value", "").strip():
        return False
    field["value"] = clean
    field["provenance"] = "system_seeded"
    return True


def _append_contract_items(contract: dict, section_key: str, field_key: str, values: list[str]) -> bool:
    field = contract.get(section_key, {}).get("fields", {}).get(field_key)
    if not field or field.get("type") != "list":
        return False
    existing = {item.get("text", "").strip().lower() for item in field.get("items", [])}
    changed = False
    for value in values:
        clean = _compact_text(value, 280)
        if not clean or clean.lower() in existing:
            continue
        field.setdefault("items", []).append(list_item(clean, "system_seeded"))
        existing.add(clean.lower())
        changed = True
    if changed:
        field["provenance"] = "system_seeded"
    return changed


def _seed_attention_workflow(project: Project, workflow: Workflow) -> None:
    workflow.nodes.clear()
    workflow.edges.clear()
    db.session.flush()
    subject = _subject_label(project)
    start = _attention_workflow_node(
        workflow,
        "start",
        "Agent brief received",
        80,
        120,
        "System",
        f"The agent brief for {subject} is ready to organize.",
        "Agent brief context is ready.",
    )
    plan = _attention_workflow_node(
        workflow,
        "agent_action",
        "Organize agent requirements",
        340,
        120,
        "Agent",
        "Turn the brief into editable features, screens, data, workflow steps, and acceptance criteria.",
        "Agent requirements are organized.",
    )
    review = _attention_workflow_node(
        workflow,
        "user_action",
        "Review generated details",
        620,
        120,
        "Human",
        "The user reviews or edits the generated agent details before export.",
        "Reviewed agent details are recorded.",
        "Send unclear or unwanted details back for editing.",
    )
    end = _attention_workflow_node(
        workflow,
        "end",
        "Agent handoff ready",
        900,
        120,
        "System",
        "The agent brief and workflow are ready for export or implementation handoff.",
        "Agent handoff is ready.",
    )
    _attention_workflow_edge(workflow, start, plan, "Begin", 1, True)
    _attention_workflow_edge(workflow, plan, review, "Draft ready", 1, True)
    _attention_workflow_edge(workflow, review, end, "Ready", 1, True)
    workflow.status = "ready"
    workflow.viewport_json = {"zoom": 0.92, "pan_x": 20, "pan_y": 20}


def _attention_workflow_node(
    workflow: Workflow,
    node_type: str,
    label: str,
    x: float,
    y: float,
    actor: str,
    description: str,
    expected_output: str,
    recovery_behavior: str = "",
) -> WorkflowNode:
    node = WorkflowNode(
        workflow=workflow,
        node_type=node_type,
        label=label,
        actor=actor,
        description=description,
        position_x=x,
        position_y=y,
        configuration_json={
            "expected_input": "Current agent brief context",
            "expected_output": expected_output,
            "data_accessed": "Agent brief, workflow steps, and saved background info",
            "permission_level": "review",
            "confidence_behavior": "Continue when the next step is clear; ask for help when important details are missing.",
            "user_visible_status": expected_output,
            "recovery_behavior": recovery_behavior or "Keep previous values available and route unclear details back to the user.",
        },
    )
    db.session.add(node)
    db.session.flush()
    return node


def _attention_workflow_edge(
    workflow: Workflow,
    source: WorkflowNode,
    target: WorkflowNode,
    label: str,
    priority: int,
    default: bool = False,
) -> None:
    db.session.add(
        WorkflowEdge(
            workflow=workflow,
            source_node_id=source.id,
            target_node_id=target.id,
            condition_label=label,
            priority=priority,
            is_default=default,
        )
    )


def _default_actor_for_node_type(node_type: str) -> str:
    return {
        "start": "System",
        "user_action": "Human",
        "agent_action": "Agent",
        "tool_call": "Tool",
        "decision": "Human",
        "confidence_check": "Agent",
        "system_message": "System",
        "escalation": "Human",
        "error": "System",
        "end": "System",
    }.get(node_type, "System")


def _first_synthesis_text(project: Project, categories: list[str]) -> str:
    for category in categories:
        value = next(
            (
                item.text.strip()
                for item in project.synthesis_items
                if item.category == category and item.inclusion_status == "included" and item.text.strip()
            ),
            "",
        )
        if value:
            return value
    return ""


def _first_nonempty_values(primary: list[str], fallback: list[str]) -> list[str]:
    values = _unique_values([_compact_text(value, 280) for value in primary if _compact_text(value, 280)])
    if values:
        return values
    return fallback


def _source_text_from_project(project: Project) -> str:
    parts = [
        f"Agent name: {project.name}",
        f"Build type: {project.workflow_name}" if project.workflow_name and project.workflow_name != "Build plan" else "",
        f"Audience: {project.target_user}" if project.target_user else "",
        f"Outcome: {project.desired_outcome}" if project.desired_outcome else "",
        f"Description: {project.description}" if project.description else "",
    ]
    text = "\n".join(part for part in parts if part)
    return text or f"Agent name: {project.name}"


def _attention_context(project: Project) -> str:
    parts = [
        project.name,
        "" if project.workflow_name == "Build plan" else project.workflow_name,
        project.target_user,
        project.desired_outcome,
        project.description,
    ]
    parts.extend(
        item.text
        for item in project.synthesis_items
        if item.inclusion_status == "included" and item.text.strip()
    )
    return _compact_text(" ".join(part for part in parts if part), 1200)


def _infer_attention_artifact_type(text: str) -> str:
    lower = text.lower()
    if any(word in lower for word in ["website", "site", "landing page", "portfolio"]):
        return "Website"
    if any(word in lower for word in ["agent", "assistant", "copilot", "chatbot"]):
        return "AI agent"
    if any(word in lower for word in ["automation", "workflow"]):
        return "Automation workflow"
    if any(word in lower for word in ["dashboard", "portal", "tool", "crm", "app", "application"]):
        return "Application"
    return "AI agent"


def _subject_label(project: Project) -> str:
    for value in [project.workflow_name if project.workflow_name != "Build plan" else "", project.desired_outcome, project.name]:
        clean = _compact_text(value, 90)
        if clean:
            return clean
    return "agent"


def _compact_text(value: str, max_length: int) -> str:
    clean = " ".join(str(value or "").split())
    if len(clean) <= max_length:
        return clean
    return clean[:max_length].rstrip(" ,.;:-")


def _contract_has_content(contract: ExperienceContract) -> bool:
    for section in (contract.content_json or {}).values():
        for field in section.get("fields", {}).values():
            if field.get("type") == "list" and field.get("items"):
                return True
            if field.get("type") == "text" and field.get("value", "").strip():
                return True
    return False


def _finding_attention_node(project: Project, node_ids: set[str]) -> WorkflowNode | None:
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "observation": 4}
    open_findings = sorted(
        (finding for finding in project.findings if finding.status == "open" and finding.related_workflow_node_id),
        key=lambda finding: severity_order.get(finding.severity, 5),
    )
    for finding in open_findings:
        if finding.related_workflow_node_id not in node_ids:
            continue
        node = db.session.get(WorkflowNode, finding.related_workflow_node_id)
        if node:
            return node
    return None


def _workflow_node_needs_detail(node: WorkflowNode) -> bool:
    config = node.configuration_json or {}
    required_fields = [
        node.label,
        node.actor,
        node.description,
        config.get("expected_input", ""),
        config.get("expected_output", ""),
        config.get("data_accessed", ""),
        config.get("permission_level", ""),
        config.get("user_visible_status", ""),
    ]
    return any(not str(value or "").strip() for value in required_fields)


def _workflow_attention_score(node: WorkflowNode) -> int:
    config = node.configuration_json or {}
    text = " ".join(
        str(value or "")
        for value in [
            node.label,
            node.description,
            node.actor,
            config.get("expected_input", ""),
            config.get("expected_output", ""),
            config.get("confidence_behavior", ""),
            config.get("user_visible_status", ""),
            config.get("recovery_behavior", ""),
        ]
    ).lower()
    score = 0
    weighted_terms = {
        "missing": 10,
        "clarif": 9,
        "resolve": 8,
        "recovery": 8,
        "review": 7,
        "risk": 6,
        "conflict": 6,
        "edit": 5,
        "human": 4,
        "confidence": 3,
    }
    for term, weight in weighted_terms.items():
        if term in text:
            score += weight
    if node.node_type in {"escalation", "decision", "confidence_check", "user_action"}:
        score += 4
    return score


def _health_check(key: str, label: str, value) -> dict:
    if isinstance(value, str):
        complete = bool(value.strip())
    else:
        complete = bool(value)
    return {"key": key, "label": label, "complete": complete}


def _decision(label: str, value, state: str) -> dict:
    items = value if isinstance(value, list) else []
    text = "" if isinstance(value, list) else str(value or "").strip()
    if not items and not text:
        state = "missing"
    state_labels = {
        "from_input": "From your input",
        "user_confirmed": "User confirmed",
        "ai_draft": "AI draft",
        "missing": "Missing",
    }
    source_labels = {
        "from_input": "Directly supplied by the project brief.",
        "user_confirmed": "Edited or confirmed in UAX Studio.",
        "ai_draft": "Suggested by the draft helper.",
        "missing": "No value has been captured yet.",
    }
    return {
        "label": label,
        "text": text,
        "items": items,
        "state": state,
        "state_label": state_labels.get(state, "Needs review"),
        "source": source_labels.get(state, "Generated or inferred detail."),
    }


def _field_state(contract: dict, section_key: str, field_key: str) -> str:
    field = contract.get(section_key, {}).get("fields", {}).get(field_key, {})
    if field.get("type") == "list":
        if not _contract_list_values(contract, section_key, field_key):
            return "missing"
    elif not field.get("value", "").strip():
        return "missing"
    return "user_confirmed" if field.get("provenance") == "user_written" else "ai_draft"


def _project_type(project: Project, contract: dict) -> str:
    if project.workflow_name and project.workflow_name != "Build plan":
        return project.workflow_name
    return _contract_text(contract, "build_target", "artifact_type")


def _contract_text(contract: dict, section_key: str, field_key: str) -> str:
    return (
        contract.get(section_key, {})
        .get("fields", {})
        .get(field_key, {})
        .get("value", "")
        .strip()
    )


def _contract_list_values(contract: dict, section_key: str, field_key: str) -> list[str]:
    field = contract.get(section_key, {}).get("fields", {}).get(field_key, {})
    if field.get("type") != "list":
        value = field.get("value", "").strip()
        return [value] if value else []
    return [item.get("text", "").strip() for item in field.get("items", []) if item.get("text", "").strip()]


def _synthesis_texts(project: Project, category: str) -> list[str]:
    return [
        item.text.strip()
        for item in project.synthesis_items
        if item.category == category and item.inclusion_status == "included" and item.text.strip()
    ]


def _unique_values(values: list[str]) -> list[str]:
    seen = set()
    unique = []
    for value in values:
        normalized = value.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        unique.append(value)
    return unique


def archive_project(project: Project) -> None:
    project.status = "archived"
    project.archived_at = utcnow()
    record_activity(project, "project_archived", "Build brief archived.")


def restore_project(project: Project) -> None:
    project.status = "active"
    project.archived_at = None
    record_activity(project, "project_restored", "Build brief restored.")


def duplicate_project(project: Project) -> Project:
    duplicate = create_project(
        name=f"{project.name} Copy",
        description=project.description,
        workflow_name=project.workflow_name,
        target_user=project.target_user,
        desired_outcome=project.desired_outcome,
    )
    for source in project.source_documents:
        db.session.add(
            SourceDocument(
                project=duplicate,
                title=source.title,
                description=source.description,
                source_type=source.source_type,
                original_filename=source.original_filename,
                stored_filename="",
                mime_type=source.mime_type,
                file_size=source.file_size,
                extracted_text=source.extracted_text,
                edited_text=source.edited_text,
                extraction_status=source.extraction_status,
                extraction_error=source.extraction_error,
            )
        )
    for item in project.synthesis_items:
        db.session.add(
            SynthesisItem(
                project=duplicate,
                category=item.category,
                text=item.text,
                source_locator=item.source_locator,
                is_inference=item.is_inference,
                confidence=item.confidence,
                inclusion_status=item.inclusion_status,
            )
        )
    if project.active_contract:
        duplicate.active_contract.content_json = copy.deepcopy(project.active_contract.content_json)
        duplicate.active_contract.status = project.active_contract.status
    if project.active_workflow:
        _copy_workflow(project.active_workflow, duplicate.active_workflow)
    record_activity(duplicate, "project_duplicated", f"Build brief duplicated from {project.name}.")
    update_project_stage(duplicate)
    return duplicate


def permanently_delete_project(project: Project) -> None:
    upload_dir = current_app.config["AX_UPLOAD_DIR"]
    export_dir = current_app.config["AX_EXPORT_DIR"]
    for source in project.source_documents:
        if source.stored_filename:
            remove_tree_safely(upload_dir, upload_dir / source.stored_filename)
    for export in project.exports:
        zip_path = Path(export.local_path)
        remove_tree_safely(export_dir, zip_path)
        bundle_dir = zip_path.with_suffix("")
        if bundle_dir.exists():
            remove_tree_safely(export_dir, bundle_dir)
    db.session.delete(project)


def _copy_workflow(source: Workflow, target: Workflow) -> None:
    target.name = source.name
    target.status = source.status
    target.viewport_json = copy.deepcopy(source.viewport_json)
    db.session.flush()
    id_map = {}
    for node in source.nodes:
        clone = WorkflowNode(
            workflow=target,
            node_type=node.node_type,
            label=node.label,
            description=node.description,
            actor=node.actor,
            configuration_json=copy.deepcopy(node.configuration_json),
            position_x=node.position_x,
            position_y=node.position_y,
        )
        db.session.add(clone)
        db.session.flush()
        id_map[node.id] = clone.id
    for edge in source.edges:
        db.session.add(
            WorkflowEdge(
                workflow=target,
                source_node_id=id_map[edge.source_node_id],
                target_node_id=id_map[edge.target_node_id],
                condition_label=edge.condition_label,
                priority=edge.priority,
                is_default=edge.is_default,
            )
        )


def seed_demo_project(reset: bool = False) -> Project:
    existing = Project.query.filter_by(slug="galleryflow-artist-submission-coordination").first()
    if existing and not reset:
        return existing
    if existing and reset:
        permanently_delete_project(existing)
        db.session.flush()

    project = create_project(
        name="GalleryFlow: Artist Submission Coordination",
        description=(
            "A fictional arts-organization workflow for normalizing inconsistent artist "
            "submissions while keeping staff review in control."
        ),
        workflow_name="Artist submission coordination",
        target_user="Submission coordinator at a small arts organization",
        desired_outcome="A source-backed artist record, clarification draft, and final team checklist.",
    )
    source_text = _demo_source_text()
    source = SourceDocument(
        project=project,
        title="GalleryFlow demo brief",
        description="Fictional source material used to seed the local demo.",
        source_type="pasted_text",
        original_filename="galleryflow-demo.md",
        stored_filename="",
        mime_type="text/markdown",
        file_size=len(source_text.encode("utf-8")),
        extracted_text=source_text,
        edited_text=source_text,
        extraction_status="ready",
    )
    db.session.add(source)
    db.session.flush()

    provider = DeterministicDemoProvider()
    synthesis = provider.generate_structured(
        task_name="intake_synthesis",
        system_prompt=get_prompt("demo_seed_synthesis"),
        user_prompt=source_text,
        response_model=SynthesisResult,
    )
    for item in dump_model(synthesis)["items"]:
        db.session.add(
            SynthesisItem(
                project=project,
                category=item["category"],
                text=item["text"],
                source_document=source if not item["is_inference"] else None,
                source_locator=item["source_reference"],
                is_inference=item["is_inference"],
                confidence=item["confidence"],
                inclusion_status="included",
            )
        )

    contract = project.active_contract
    suggestion = provider.generate_structured(
        task_name="contract_suggestions",
        system_prompt=get_prompt("demo_seed_contract"),
        user_prompt=source_text,
        response_model=ContractSuggestion,
    )
    contract.content_json = dump_model(suggestion)["content_json"]
    contract.status = "ready"

    workflow = project.active_workflow
    _seed_demo_workflow(workflow)
    _seed_demo_review(project, workflow)
    record_activity(project, "demo_seeded", "GalleryFlow demo content seeded.")
    update_project_stage(project)
    db.session.commit()
    return project


def _node(
    workflow: Workflow,
    node_type: str,
    label: str,
    x: float,
    y: float,
    actor: str,
    description: str,
    expected_output: str,
    recovery_behavior: str = "",
):
    node = WorkflowNode(
        workflow=workflow,
        node_type=node_type,
        label=label,
        actor=actor,
        description=description,
        position_x=x,
        position_y=y,
        configuration_json={
            "expected_input": "Current submission context",
            "expected_output": expected_output,
            "data_accessed": "Uploaded source text and project state",
            "permission_level": "review",
            "confidence_behavior": "Pause for staff review when confidence is low.",
            "user_visible_status": expected_output,
            "recovery_behavior": recovery_behavior,
        },
    )
    db.session.add(node)
    db.session.flush()
    return node


def _edge(workflow: Workflow, source: WorkflowNode, target: WorkflowNode, label: str, priority: int, default=False):
    db.session.add(
        WorkflowEdge(
            workflow=workflow,
            source_node_id=source.id,
            target_node_id=target.id,
            condition_label=label,
            priority=priority,
            is_default=default,
        )
    )


def _seed_demo_workflow(workflow: Workflow) -> None:
    workflow.nodes.clear()
    workflow.edges.clear()
    db.session.flush()
    start = _node(workflow, "start", "Submission received", 80, 120, "System", "A new artist package is available.", "Ready to inspect submission.")
    parse = _node(workflow, "tool_call", "Parse submitted materials", 330, 120, "Tool", "Extract text from supported forms, spreadsheets, and attachments.", "Extracted fields and source references.", "If parsing fails, preserve files and allow manual entry.")
    confidence = _node(workflow, "confidence_check", "Check extraction confidence", 610, 120, "Agent", "Compare extracted fields with source quality.", "Confidence label and reasons.")
    identity = _node(workflow, "user_action", "Review normalized artist identity", 900, 60, "Human", "Staff reviews identity normalization.", "Reviewed identity.", "Unclear identity returns to staff edits.")
    missing = _node(workflow, "decision", "Missing or conflicting details?", 1180, 120, "Human", "Staff decides whether the record can continue.", "Complete, missing, or conflicting.")
    draft = _node(workflow, "agent_action", "Draft clarification request", 1450, 40, "Agent", "Prepare a source-backed clarification request.", "Draft email preview for staff review.", "Do not send externally until reviewed.")
    clarify = _node(workflow, "user_action", "Review clarification request", 1720, 40, "Human", "Staff reviews or edits the draft.", "Reviewed clarification request.")
    edits = _node(workflow, "user_action", "Staff edits recommendation", 1450, 230, "Human", "Staff corrects fields or changes a provider suggestion.", "Updated draft state.", "Previous values remain available.")
    preview = _node(workflow, "agent_action", "Prepare normalized record preview", 1720, 230, "Agent", "Compile normalized data with evidence.", "Preview of final record.")
    record = _node(workflow, "user_action", "Finalize completed artwork record", 2000, 230, "Human", "Staff reviews the record before it becomes final.", "Final record.")
    checklist = _node(workflow, "user_action", "Finalize checklist export", 2280, 230, "Human", "Staff reviews the implementation checklist export.", "Final checklist export.")
    error = _node(workflow, "error", "File parsing fails", 610, 340, "System", "A source file cannot be parsed.", "Parsing failure visible to staff.", "Offer manual entry and keep original file.")
    recovery = _node(workflow, "escalation", "Manual recovery", 900, 340, "Human", "Staff enters missing fields or replaces the file.", "Recovered submission context.")
    end = _node(workflow, "end", "Submission package ready", 2570, 230, "System", "The implementation package is ready.", "Normalized record and checklist are complete.")

    _edge(workflow, start, parse, "Begin", 1, True)
    _edge(workflow, parse, confidence, "Parsed", 1, True)
    _edge(workflow, parse, error, "Parsing fails", 2)
    _edge(workflow, confidence, identity, "High or medium confidence", 1, True)
    _edge(workflow, confidence, recovery, "Low confidence escalate", 2)
    _edge(workflow, identity, missing, "Reviewed", 1, True)
    _edge(workflow, identity, edits, "Needs edits", 2)
    _edge(workflow, missing, preview, "Complete", 1, True)
    _edge(workflow, missing, draft, "Missing or conflicting", 2)
    _edge(workflow, draft, clarify, "Draft ready", 1, True)
    _edge(workflow, clarify, preview, "Ready", 1, True)
    _edge(workflow, clarify, edits, "Needs edits", 2)
    _edge(workflow, edits, missing, "Updated", 1, True)
    _edge(workflow, preview, record, "Preview ready", 1, True)
    _edge(workflow, record, checklist, "Ready", 1, True)
    _edge(workflow, record, edits, "Needs edits", 2)
    _edge(workflow, checklist, end, "Ready", 1, True)
    _edge(workflow, checklist, recovery, "Needs recovery", 2)
    _edge(workflow, error, recovery, "Recover manually", 1, True)
    _edge(workflow, recovery, end, "Safe completion", 1, True)
    workflow.status = "ready"
    workflow.viewport_json = {"zoom": 0.72, "pan_x": 24, "pan_y": 30}


def _seed_demo_review(project: Project, workflow: Workflow) -> None:
    run = ReviewRun(
        project=project,
        reviewer_type="trust_safety_critic",
        contract_version=project.active_contract.version_number,
        workflow_version=workflow.version_number,
        status="complete",
        provider_name="deterministic",
        completed_at=utcnow(),
    )
    db.session.add(run)
    db.session.flush()
    db.session.add(
        Finding(
            review_run=run,
            project=project,
            category="Trust and safety",
            severity="high",
            title="Outbound clarification needs a visible review record",
            explanation=(
                "The workflow correctly routes clarification requests through staff review, but the exported "
                "implementation package should preserve the reviewer and timestamp requirement."
            ),
            evidence="Review clarification request node and autonomy controls.",
            related_contract_section="autonomy_controls",
            recommendation="Include reviewer, decision, timestamp, and edited draft text in the implementation spec.",
            status="open",
        )
    )


def _demo_source_text() -> str:
    return """# GalleryFlow demo brief

An arts organization receives artist submissions through inconsistent forms, email
attachments, and spreadsheets. Staff manually copy artist information, check whether
required fields are present, request corrections, organize artwork records, and prepare
a final team checklist.

The agent may extract artist and artwork information, normalize fields, identify
missing or conflicting information, draft a clarification request, propose checklist
entries, and prepare a preview of the normalized record.

The agent may not send an email without staff confirmation, change an artist's
submitted biography silently, invent missing dimensions, prices, materials, or
contact information, publish an artwork record without staff review, or delete
original source material.

Review checkpoints are required for normalized artist identity, proposed
corrections, outgoing clarification requests, completed artwork records, and
final checklist export.
"""
