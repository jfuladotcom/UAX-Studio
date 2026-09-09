from __future__ import annotations

from uuid import uuid4

from app.extensions import db
from app.models import Project, SourceDocument, Workflow, WorkflowEdge, WorkflowNode, utcnow
from app.services.build_instructions_service import generate_build_instructions
from app.services.contract_service import ensure_contract_shape
from app.services.extraction import normalize_pasted_text, preview_jsonish_text
from app.services.project_service import create_project, record_activity, update_project_stage


def create_simple_project(
    *,
    name: str,
    brief: str,
    build_type: str = "",
    target_user: str = "",
    desired_outcome: str = "",
) -> dict:
    text = normalize_pasted_text(brief)
    if not text:
        raise ValueError("Describe what you want to build.")

    build_type = build_type.strip()
    context_text = "\n".join(
        part
        for part in [
            f"Build type: {build_type}" if build_type else "",
            f"Target user: {target_user}" if target_user else "",
            f"Desired outcome: {desired_outcome}" if desired_outcome else "",
            text,
        ]
        if part
    )

    project = create_project(
        name=name.strip() or _infer_name(text),
        description=_brief_description(text),
        workflow_name=_workflow_name_for_type(build_type),
        target_user=target_user,
        desired_outcome=desired_outcome,
    )
    source = SourceDocument(
        project=project,
        title="Starting idea",
        description="Initial build request entered in the guided brief.",
        source_type="pasted_text",
        original_filename="",
        stored_filename="",
        mime_type="text/plain",
        file_size=len(context_text.encode("utf-8")),
        extracted_text=context_text,
        edited_text=preview_jsonish_text(context_text),
        extraction_status="ready",
    )
    db.session.add(source)
    db.session.flush()

    active_contract = project.active_contract
    generation = generate_build_instructions(active_contract)
    _fill_project_summary(project)
    active_contract.content_json = _apply_simple_build_defaults(
        ensure_contract_shape(active_contract.content_json),
        build_type,
        target_user,
        desired_outcome,
    )
    active_contract.status = "draft"
    active_contract.updated_at = utcnow()

    _seed_simple_workflow(project)

    provider_names = generation["providers"]
    notice = generation["notice"]
    record_activity(
        project,
        "simple_mode_draft_created",
        "Build plan generated from starting idea.",
        {"providers": provider_names, "notice": notice},
    )
    update_project_stage(project)
    return {"project": project, "providers": provider_names, "notice": notice}


def _fill_project_summary(project: Project) -> None:
    first_user = _first_synthesis_text(project, "users")
    first_goal = _first_synthesis_text(project, "goals")
    first_task = _first_synthesis_text(project, "tasks")
    if not project.target_user and first_user:
        project.target_user = first_user[:240]
    if not project.desired_outcome and first_goal:
        project.desired_outcome = first_goal
    if first_task:
        project.workflow_name = _short_label(first_task, "Build plan")
        if project.active_workflow:
            project.active_workflow.name = project.workflow_name


def _first_synthesis_text(project: Project, category: str) -> str:
    item = next(
        (
            candidate
            for candidate in project.synthesis_items
            if candidate.category == category and candidate.inclusion_status == "included"
        ),
        None,
    )
    return item.text if item else ""


def _seed_simple_workflow(project: Project) -> None:
    workflow = project.active_workflow
    if not workflow:
        return
    workflow.nodes.clear()
    workflow.edges.clear()
    db.session.flush()

    subject = _short_label(project.desired_outcome or project.workflow_name or project.name, "build request")
    start = _workflow_node(
        workflow,
        "start",
        "Build brief received",
        80,
        120,
        "System",
        f"A user describes the product they want to build for {subject}.",
        "Build request context is ready.",
    )
    draft = _workflow_node(
        workflow,
        "agent_action",
        "Extract build requirements",
        330,
        120,
        "Agent",
        "Turn the brief into editable users, features, surfaces, data, constraints, and open questions.",
        "Editable implementation requirements with source notes.",
    )
    confidence = _workflow_node(
        workflow,
        "confidence_check",
        "Organize build details",
        610,
        120,
        "Agent",
        "Summarize what is clear, what is missing, and what should stay visible for the builder.",
        "Organized build details, missing details, and risk notes.",
        recovery_behavior="Route missing platform, data, integration, auth, or scope decisions to a human.",
    )
    review = _workflow_node(
        workflow,
        "user_action",
        "Review build brief",
        900,
        80,
        "Human",
        "The user edits what to build, core features, steps, and scope.",
        "Reviewed build brief content.",
        permission_level="review",
        recovery_behavior="Unclear build details return to clarification.",
    )
    complete = _workflow_node(
        workflow,
        "agent_action",
        "Prepare AI build Markdown",
        1180,
        80,
        "Agent",
        "Package the build instructions, steps, and acceptance checks into the AI build brief.",
        "AI_BUILD_BRIEF.md is ready to download.",
        permission_level="review",
    )
    recovery = _workflow_node(
        workflow,
        "escalation",
        "Resolve missing build detail",
        900,
        250,
        "Human",
        "A human fills missing platform, screen, feature, data, integration, or deployment details.",
        "Clarified build details are recorded.",
        permission_level="review",
        recovery_behavior="Keep the current build brief visible and preserve previous values.",
    )
    end = _workflow_node(
        workflow,
        "end",
        "Build brief ready",
        1450,
        120,
        "System",
        "The Markdown brief is ready for an AI builder or engineering handoff.",
        "Build plan is complete.",
    )

    _workflow_edge(workflow, start, draft, "Begin", 1, True)
    _workflow_edge(workflow, draft, confidence, "Draft ready", 1, True)
    _workflow_edge(workflow, confidence, review, "Build-ready enough", 1, True)
    _workflow_edge(workflow, confidence, recovery, "Missing or risky build detail", 2)
    _workflow_edge(workflow, review, complete, "Ready", 1, True)
    _workflow_edge(workflow, review, recovery, "Needs edits", 2)
    _workflow_edge(workflow, complete, end, "Export ready", 1, True)
    _workflow_edge(workflow, recovery, review, "Clarified", 1, True)
    workflow.status = "ready"
    workflow.viewport_json = {"zoom": 0.9, "pan_x": 20, "pan_y": 20}


def _workflow_node(
    workflow: Workflow,
    node_type: str,
    label: str,
    x: float,
    y: float,
    actor: str,
    description: str,
    expected_output: str,
    permission_level: str = "review",
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
            "expected_input": "Current build brief context",
            "expected_output": expected_output,
            "data_accessed": "Project source text and build decisions",
            "permission_level": permission_level,
            "confidence_behavior": "Continue on medium or high confidence; escalate low or unknown confidence.",
            "user_visible_status": expected_output,
            "recovery_behavior": recovery_behavior,
        },
    )
    db.session.add(node)
    db.session.flush()
    return node


def _workflow_edge(
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


def _contract_list(contract: dict, section_key: str, field_key: str) -> list[str]:
    field = contract.get(section_key, {}).get("fields", {}).get(field_key, {})
    if field.get("type") == "list":
        return [item.get("text", "") for item in field.get("items", []) if item.get("text", "").strip()]
    value = field.get("value", "").strip()
    return [value] if value else []


def _infer_name(text: str) -> str:
    for line in text.splitlines():
        cleaned = line.strip(" #\t:-")
        if cleaned:
            return _short_label(cleaned, "Untitled build")
    return "Untitled build"


def _workflow_name_for_type(build_type: str) -> str:
    cleaned = build_type.strip()
    return f"{cleaned} build plan" if cleaned else "Build plan"


def _apply_simple_build_defaults(contract: dict, build_type: str, target_user: str, desired_outcome: str) -> dict:
    if build_type:
        _set_contract_text(contract, "build_target", "artifact_type", build_type)
    if target_user:
        _set_contract_text(contract, "product_intent", "target_user", target_user)
    if desired_outcome:
        _set_contract_text(contract, "product_intent", "desired_outcome", desired_outcome)
    if not _contract_list(contract, "implementation_plan", "out_of_scope"):
        _set_contract_list(
            contract,
            "implementation_plan",
            "out_of_scope",
            ["Features, integrations, or production actions not specified in this brief."],
        )
    if not _contract_list(contract, "implementation_plan", "ai_builder_instructions"):
        _set_contract_text(
            contract,
            "implementation_plan",
            "ai_builder_instructions",
            "Use AI_BUILD_BRIEF.md as the source of truth for building the target product. Do not build UAX Studio itself unless the user explicitly asks for that.",
        )
    return contract


def _set_contract_text(contract: dict, section_key: str, field_key: str, value: str) -> None:
    field = contract.get(section_key, {}).get("fields", {}).get(field_key)
    if not field:
        return
    field["value"] = value
    field["provenance"] = "user_written"


def _set_contract_list(contract: dict, section_key: str, field_key: str, values: list[str]) -> None:
    field = contract.get(section_key, {}).get("fields", {}).get(field_key)
    if not field:
        return
    field["items"] = [
        {
            "id": str(uuid4()),
            "text": value,
            "provenance": "provider_suggested",
        }
        for value in values
    ]


def _brief_description(text: str) -> str:
    return " ".join(text.split())[:420]


def _short_label(text: str, fallback: str) -> str:
    words = [word.strip(".,:;()[]{}") for word in text.split() if word.strip(".,:;()[]{}")]
    if not words:
        return fallback
    label = " ".join(words[:7])
    return label[:160] or fallback
