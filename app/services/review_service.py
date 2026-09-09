from __future__ import annotations

import json

from app.extensions import db
from app.models import Finding, Project, ReviewRun, utcnow
from app.schemas import ProviderFailure, ReviewResult, dump_model
from app.services.project_service import record_activity, update_project_stage
from app.services.prompt_service import get_prompt
from app.services.providers import DeterministicDemoProvider, get_provider

REVIEWERS = {
    "interaction_architect": "Interaction Architect",
    "trust_safety_critic": "Trust and Safety Critic",
    "accessibility_reviewer": "Accessibility Reviewer",
    "technical_feasibility_reviewer": "Technical Feasibility Reviewer",
}


def run_review(project: Project, reviewer_type: str) -> ReviewRun:
    if reviewer_type not in REVIEWERS:
        raise ValueError("Unknown reviewer.")
    provider = get_provider()
    contract = project.active_contract
    workflow = project.active_workflow
    run = ReviewRun(
        project=project,
        reviewer_type=reviewer_type,
        contract_version=contract.version_number if contract else 1,
        workflow_version=workflow.version_number if workflow else 1,
        status="running",
        provider_name=provider.name,
    )
    db.session.add(run)
    db.session.flush()

    try:
        result = provider.generate_structured(
            task_name=f"review_{reviewer_type}",
            system_prompt=get_prompt("review_quality"),
            user_prompt=_review_context(project),
            response_model=ReviewResult,
        )
    except ProviderFailure as exc:
        fallback = DeterministicDemoProvider()
        result = fallback.generate_structured(
            task_name=f"review_{reviewer_type}",
            system_prompt=get_prompt("fallback_review"),
            user_prompt=_review_context(project),
            response_model=ReviewResult,
        )
        run.provider_name = "deterministic"
        run.error_message = f"{exc.message} Fallback deterministic review was used."

    node_reference_lookup = _workflow_node_reference_lookup(workflow)
    for item in dump_model(result)["findings"]:
        related_node = str(item.get("related_workflow_node_id") or "").strip()
        db.session.add(
            Finding(
                review_run=run,
                project=project,
                category=item["category"],
                severity=item["severity"],
                title=item["title"],
                explanation=item["explanation"],
                evidence=item["evidence"],
                related_contract_section=item.get("related_contract_section", ""),
                related_workflow_node_id=node_reference_lookup.get(related_node)
                or node_reference_lookup.get(related_node.lower()),
                recommendation=item["recommendation"],
                status="open",
            )
        )
    run.status = "complete"
    run.completed_at = utcnow()
    record_activity(project, "review_completed", f"Quality check completed: {REVIEWERS[reviewer_type]}.")
    update_project_stage(project)
    return run


def run_all_reviews(project: Project) -> list[ReviewRun]:
    return [run_review(project, reviewer_type) for reviewer_type in REVIEWERS]


def _workflow_node_reference_lookup(workflow) -> dict[str, str]:
    if not workflow:
        return {}
    nodes = list(workflow.nodes)
    lookup = {node.id: node.id for node in nodes}
    by_label: dict[str, list[str]] = {}
    for node in nodes:
        label = node.label.strip().lower()
        if label:
            by_label.setdefault(label, []).append(node.id)
    for label, node_ids in by_label.items():
        if len(node_ids) == 1:
            lookup[label] = node_ids[0]
    return lookup


def _review_context(project: Project) -> str:
    contract = project.active_contract.content_json if project.active_contract else {}
    workflow = project.active_workflow
    node_labels = ", ".join(node.label for node in workflow.nodes) if workflow else ""
    return (
        f"Project: {project.name}\n"
        f"Target user: {project.target_user}\n"
        f"Outcome: {project.desired_outcome}\n"
        f"Original description: {project.description}\n"
        f"Build Instructions: {json.dumps(contract, ensure_ascii=False)}\n"
        f"Workflow nodes: {node_labels}\n"
    )
