from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
import zipfile
from datetime import timezone
from pathlib import Path
from uuid import uuid4

from flask import current_app

from app.extensions import db
from app.models import ExportRecord, Project, utcnow
from app.services.contract_service import ensure_contract_shape
from app.services.project_service import record_activity, update_project_stage
from app.services.security import ensure_within_directory, safe_display_filename, slugify
from app.services.workflow_service import serialize_workflow

EXPORT_FILES = [
    "README.md",
    "product_intent.md",
    "build_contract.md",
    "agent_experience_contract.md",
    "workflow.md",
    "workflow.mmd",
    "workflow.json",
    "findings.md",
    "acceptance_criteria.md",
    "implementation_manifest.json",
    "AI_BUILD_BRIEF.md",
]


def build_export(project: Project, include_sources: bool = False) -> ExportRecord:
    now = utcnow()
    export_dir = current_app.config["AX_EXPORT_DIR"]
    export_id = str(uuid4())
    folder_name = (
        f"{slugify(project.name)}-{now.strftime('%Y%m%dT%H%M%S%fZ')}-{export_id[:8]}"
    )
    bundle_dir = ensure_within_directory(export_dir, export_dir / folder_name)
    zip_path = ensure_within_directory(export_dir, export_dir / f"{folder_name}.zip")
    staging_root = Path(tempfile.mkdtemp(prefix=".uax-export-", dir=export_dir))
    staging_bundle = staging_root / folder_name
    staging_zip = staging_root / f"{folder_name}.zip"

    try:
        staging_bundle.mkdir()
        files: dict[str, str | bytes] = compose_export_files(
            project, now, include_sources=include_sources
        )
        files.pop("implementation_manifest.json", None)
        if include_sources:
            files.update(_source_export_files(project))

        for relative_name, content in files.items():
            target = ensure_within_directory(staging_bundle, staging_bundle / relative_name)
            target.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(content, str):
                target.write_text(content, encoding="utf-8")
            else:
                target.write_bytes(content)

        manifest = _manifest_for_files(staging_bundle)
        manifest_path = staging_bundle / "implementation_manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        with zipfile.ZipFile(staging_zip, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(staging_bundle.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(staging_bundle).as_posix())

        staging_bundle.replace(bundle_dir)
        staging_zip.replace(zip_path)
    except Exception:
        _remove_path(bundle_dir)
        _remove_path(zip_path)
        raise
    finally:
        shutil.rmtree(staging_root, ignore_errors=True)

    record = ExportRecord(
        id=export_id,
        project=project,
        contract_version=project.active_contract.version_number if project.active_contract else 1,
        workflow_version=project.active_workflow.version_number if project.active_workflow else 1,
        export_type="zip",
        local_path=str(zip_path),
        manifest_json=manifest,
    )
    db.session.add(record)
    record_activity(project, "export_created", "Export package created.", {"include_sources": include_sources})
    update_project_stage(project)
    return record


def discard_export_artifacts(record: ExportRecord) -> None:
    export_dir = current_app.config["AX_EXPORT_DIR"]
    zip_path = ensure_within_directory(export_dir, Path(record.local_path))
    _remove_path(zip_path)
    _remove_path(zip_path.with_suffix(""))


def compose_export_files(
    project: Project, timestamp, include_sources: bool = False
) -> dict[str, str]:
    workflow = project.active_workflow
    workflow_data = serialize_workflow(workflow) if workflow else {"nodes": [], "edges": []}
    finding_data = [_finding_to_dict(finding) for finding in project.findings]
    contract = ensure_contract_shape(project.active_contract.content_json if project.active_contract else {})
    metadata = _metadata(project, timestamp)
    build_brief = _ai_build_brief(project, contract, workflow_data, finding_data, metadata)
    files = {
        "README.md": _readme(project, metadata, include_sources),
        "product_intent.md": _product_intent(project, contract, metadata),
        "build_contract.md": _contract_md(project, contract, metadata),
        "agent_experience_contract.md": _contract_md(project, contract, metadata),
        "workflow.md": _workflow_md(project, workflow_data, metadata),
        "workflow.mmd": mermaid_for_workflow(workflow_data),
        "workflow.json": json.dumps({"schema_version": "1.0", "metadata": metadata, "workflow": workflow_data}, indent=2),
        "findings.md": _findings_md(project, finding_data, metadata),
        "acceptance_criteria.md": _acceptance_md(project, contract, metadata),
        "implementation_manifest.json": "{}",
        "AI_BUILD_BRIEF.md": build_brief,
    }
    return files


def _source_export_files(project: Project) -> dict[str, str | bytes]:
    files: dict[str, str | bytes] = {}
    used_paths: set[str] = set()
    upload_dir = current_app.config["AX_UPLOAD_DIR"]

    for source in project.source_documents:
        text_name = _unique_export_name(f"{slugify(source.title)}.txt", used_paths, "sources/text")
        files[f"sources/text/{text_name}"] = source.edited_text or source.extracted_text

        if not source.stored_filename:
            continue
        original_path = ensure_within_directory(upload_dir, upload_dir / source.stored_filename)
        if not original_path.is_file():
            continue
        original_name = _unique_export_name(
            safe_display_filename(source.original_filename), used_paths, "sources/originals"
        )
        files[f"sources/originals/{original_name}"] = original_path.read_bytes()
    return files


def _unique_export_name(filename: str, used_paths: set[str], directory: str) -> str:
    safe_name = safe_display_filename(filename)
    stem = Path(safe_name).stem or "source"
    suffix = Path(safe_name).suffix
    candidate = safe_name
    counter = 2
    while f"{directory}/{candidate}".lower() in used_paths:
        candidate = f"{stem}-{counter}{suffix}"
        counter += 1
    used_paths.add(f"{directory}/{candidate}".lower())
    return candidate


def _remove_path(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def _metadata(project: Project, timestamp) -> dict:
    return {
        "project_id": project.id,
        "project_name": project.name,
        "export_timestamp": timestamp.astimezone(timezone.utc).isoformat(),
        "contract_version": project.active_contract.version_number if project.active_contract else 1,
        "workflow_version": project.active_workflow.version_number if project.active_workflow else 1,
    }


def _manifest_for_files(bundle_dir: Path) -> dict:
    files = []
    for path in sorted(bundle_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.name == "implementation_manifest.json":
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        files.append(
            {
                "path": path.relative_to(bundle_dir).as_posix(),
                "sha256": digest,
                "bytes": path.stat().st_size,
            }
        )
    return {
        "schema_version": "1.0",
        "notes": "Hashes cover bundle files other than this manifest file.",
        "files": files,
    }


def _readme(project: Project, metadata: dict, include_sources: bool = False) -> str:
    source_note = (
        "Selected source material is included under `sources/`. Original uploads are preserved "
        "under `sources/originals/`, and editable text copies are under `sources/text/`."
        if include_sources
        else "Source documents are excluded from this package."
    )
    return f"""# {project.name}

Exported from UAX Studio at {metadata['export_timestamp']}.

## Objective

{project.desired_outcome or project.description}

## Contents

- `AI_BUILD_BRIEF.md`: Primary Markdown handoff for an AI builder or engineering team.
- `build_contract.md`: Editable build target, implementation, and governance decisions.
- `agent_experience_contract.md`: Compatibility copy of the build contract for agent-focused workflows.
- `workflow.md` and `workflow.mmd`: Workflow states and transitions.
- `workflow.json`: Structured implementation data.
- `findings.md`: Review findings and resolution status.

{source_note}
"""


def _product_intent(project: Project, contract: dict, metadata: dict) -> str:
    section = contract.get("product_intent", {}).get("fields", {})
    return "\n".join(
        [
            f"# Product Intent: {project.name}",
            "",
            f"Export timestamp: {metadata['export_timestamp']}",
            "",
            _field_line("Problem statement", section.get("problem_statement")),
            _field_line("Target user", section.get("target_user")),
            _field_line("User goal", section.get("user_goal")),
            _field_line("Desired outcome", section.get("desired_outcome")),
            _field_line("Business objective", section.get("business_objective")),
            _list_block("Success measures", section.get("success_measures")),
            _list_block("Known constraints", section.get("known_constraints")),
        ]
    )


def _contract_md(project: Project, contract: dict, metadata: dict) -> str:
    lines = [
        f"# Build Contract: {project.name}",
        "",
        f"Contract version: {metadata['contract_version']}",
        f"Export timestamp: {metadata['export_timestamp']}",
        "",
    ]
    for section in contract.values():
        lines.append(f"## {section.get('title', 'Section')}")
        lines.append("")
        for field in section.get("fields", {}).values():
            if field.get("type") == "list":
                lines.append(_list_block(field.get("label", "Field"), field))
            else:
                lines.append(_field_line(field.get("label", "Field"), field))
            lines.append("")
    return "\n".join(lines).strip() + "\n"


def _workflow_md(project: Project, workflow: dict, metadata: dict) -> str:
    lines = [
        f"# Workflow: {project.workflow_name or project.name}",
        "",
        f"Workflow version: {metadata['workflow_version']}",
        "",
        "## Nodes",
        "",
    ]
    for node in workflow["nodes"]:
        lines.extend(
            [
                f"### {node['label']}",
                "",
                f"- ID: `{node['id']}`",
                f"- Type: `{node['node_type']}`",
                f"- Actor: {node['actor']}",
                f"- Description: {node['description'] or 'Not specified'}",
                f"- Expected output: {node['expected_output'] or 'Not specified'}",
                f"- Recovery: {node['recovery_behavior'] or 'Not specified'}",
                "",
            ]
        )
    lines.extend(["## Edges", ""])
    for edge in workflow["edges"]:
        source = _label_for_node(workflow, edge["source_node_id"])
        target = _label_for_node(workflow, edge["target_node_id"])
        lines.append(f"- `{source}` -> `{target}` when **{edge['condition_label']}**")
    return "\n".join(lines) + "\n"


def mermaid_for_workflow(workflow: dict) -> str:
    lines = ["flowchart TD"]
    for node in workflow.get("nodes", []):
        lines.append(f"  {node_id_for_mermaid(node['id'])}[{_mermaid_label(node['label'])}]")
    for edge in workflow.get("edges", []):
        lines.append(
            f"  {node_id_for_mermaid(edge['source_node_id'])} -->|{_mermaid_label(edge['condition_label'])}| {node_id_for_mermaid(edge['target_node_id'])}"
        )
    return "\n".join(lines) + "\n"


def node_id_for_mermaid(value: str) -> str:
    return "n_" + re.sub(r"[^a-zA-Z0-9_]", "_", value)


def _mermaid_label(value: str) -> str:
    return re.sub(r"[\[\]{}|<>`\"]", "", value or "Node")[:80]


def _findings_md(project: Project, findings: list[dict], metadata: dict) -> str:
    lines = [f"# Findings: {project.name}", "", f"Export timestamp: {metadata['export_timestamp']}", ""]
    if not findings:
        lines.append("No findings recorded.")
    for finding in findings:
        lines.extend(
            [
                f"## {finding['title']}",
                "",
                f"- Category: {finding['category']}",
                f"- Severity: {finding['severity']}",
                f"- Status: {finding['status']}",
                f"- Related section: {finding['related_contract_section'] or 'Not specified'}",
                "",
                finding["explanation"],
                "",
                f"Evidence: {finding['evidence']}",
                "",
                f"Recommendation: {finding['recommendation']}",
                "",
            ]
        )
    return "\n".join(lines)


def _acceptance_md(project: Project, contract: dict, metadata: dict) -> str:
    section = contract.get("definition_of_done", {}).get("fields", {})
    return "\n".join(
        [
            f"# Acceptance Criteria: {project.name}",
            "",
            f"Export timestamp: {metadata['export_timestamp']}",
            "",
            _list_block("UX acceptance criteria", section.get("ux_acceptance_criteria")),
            _list_block("Functional acceptance criteria", section.get("functional_acceptance_criteria")),
            _list_block("Open questions", section.get("open_questions")),
        ]
    )


def _ai_build_brief(project: Project, contract: dict, workflow: dict, findings: list[dict], metadata: dict) -> str:
    build = contract.get("build_target", {}).get("fields", {})
    objective = _first_text(
        project.desired_outcome,
        _field_value(contract, "product_intent", "desired_outcome"),
        project.description,
    )
    core_features = _unique_lines(
        _list_values(contract, "build_target", "core_features")
        + _list_values(contract, "definition_of_done", "functional_acceptance_criteria")
        + _synthesis_texts(project, "requirements")
        + _synthesis_texts(project, "tasks")
    )
    surfaces = _unique_lines(
        _list_values(contract, "build_target", "primary_surfaces")
        + _list_values(contract, "implementation_plan", "routes_or_views")
    )
    data_items = _unique_lines(
        _list_values(contract, "build_target", "data_entities")
        + _list_values(contract, "data_and_memory", "may_read")
        + _list_values(contract, "data_and_memory", "may_create_or_modify")
    )
    acceptance = _unique_lines(
        _list_values(contract, "implementation_plan", "acceptance_tests")
        + _list_values(contract, "definition_of_done", "functional_acceptance_criteria")
        + _list_values(contract, "definition_of_done", "ux_acceptance_criteria")
    )
    out_of_scope = _list_values(contract, "implementation_plan", "out_of_scope")
    builder_notes = _field_value(contract, "implementation_plan", "ai_builder_instructions") or (
        "Use this Markdown as the implementation source of truth. Build the target product described here, "
        "not UAX Studio itself, unless the user explicitly asks for that."
    )

    return "\n".join(
        [
            f"# AI Build Brief: {project.name}",
            "",
            "Use this Markdown as the implementation handoff for an AI builder or engineering team.",
            "",
            f"Export timestamp: {metadata['export_timestamp']}",
            f"Contract version: {metadata['contract_version']}",
            f"Workflow version: {metadata['workflow_version']}",
            "",
            "## Build Target",
            "",
            _plain_field("Build type", build.get("artifact_type")),
            _plain_field("Target platform or stack", build.get("target_platform")),
            f"**Primary user:** {project.target_user or _field_value(contract, 'product_intent', 'target_user') or 'Not specified.'}",
            f"**Desired outcome:** {objective or 'Not specified.'}",
            _plain_field("Deployment environment", build.get("deployment_environment")),
            "",
            "## Product Objective",
            "",
            objective or "Not specified.",
            "",
            "## Core Features",
            "",
            _bullet_list(core_features, "Define core features before implementation."),
            "",
            "## Screens, Pages, or Surfaces",
            "",
            _bullet_list(surfaces, "Define the primary user-facing surfaces before implementation."),
            "",
            "## Data, Content, and State",
            "",
            _bullet_list(data_items, "Define data models, content types, or state before implementation."),
            "",
            "## Integrations, Auth, and Permissions",
            "",
            _subsection_list("Integrations, tools, or APIs", _list_values(contract, "build_target", "integrations")),
            "",
            _subsection_list("Authentication, permissions, and roles", _list_values(contract, "build_target", "auth_and_roles")),
            "",
            _subsection_list("Environment variables or secrets", _list_values(contract, "build_target", "environment_variables")),
            "",
            _subsection_list("Review and confirmation rules", _list_values(contract, "autonomy_controls", "confirmation_actions")),
            "",
            "## Workflow to Implement",
            "",
            _workflow_md(project, workflow, metadata),
            "",
            "## Implementation Plan",
            "",
            _subsection_list("Steps", _list_values(contract, "implementation_plan", "implementation_steps")),
            "",
            _subsection_list("Routes, views, or modules", _list_values(contract, "implementation_plan", "routes_or_views")),
            "",
            _subsection_list("Data flow", _list_values(contract, "implementation_plan", "data_flow")),
            "",
            _subsection_list(
                "Performance, accessibility, and quality",
                _list_values(contract, "build_target", "nonfunctional_requirements"),
            ),
            "",
            "## AI or Agent Behavior, If Applicable",
            "",
            _section_summary_or_na(contract, "responsibility_model"),
            "",
            "## Failure and Recovery Behavior",
            "",
            _section_summary_or_na(contract, "escalation_and_recovery"),
            "",
            "## Acceptance Criteria",
            "",
            _bullet_list(acceptance, "Define acceptance checks before implementation."),
            "",
            "## Out of Scope",
            "",
            _bullet_list(out_of_scope, "None specified. Do not invent exclusions."),
            "",
            "## Open Questions That Still Require Human Answers",
            "",
            _open_questions(contract, findings),
            "",
            "## Instructions for the AI Builder",
            "",
            builder_notes,
            "",
            "- Treat user-written contract entries as higher priority than inferred suggestions.",
            "- Ask before adding integrations, secrets, billing flows, production deployment, or irreversible actions that are not specified above.",
            "- Keep unresolved open questions visible instead of silently filling them with assumptions.",
        ]
    )


def _first_text(*values: str) -> str:
    return next((value.strip() for value in values if value and value.strip()), "")


def _field_value(contract: dict, section_key: str, field_key: str) -> str:
    return (
        contract.get(section_key, {})
        .get("fields", {})
        .get(field_key, {})
        .get("value", "")
        .strip()
    )


def _plain_field(label: str, field: dict | None) -> str:
    value = (field or {}).get("value", "").strip() or "Not specified."
    return f"**{label}:** {value}"


def _list_values(contract: dict, section_key: str, field_key: str) -> list[str]:
    field = contract.get(section_key, {}).get("fields", {}).get(field_key, {})
    if field.get("type") == "list":
        return [item.get("text", "").strip() for item in field.get("items", []) if item.get("text", "").strip()]
    value = field.get("value", "").strip()
    return [value] if value else []


def _synthesis_texts(project: Project, category: str) -> list[str]:
    return [
        item.text.strip()
        for item in project.synthesis_items
        if item.category == category and item.inclusion_status == "included" and item.text.strip()
    ]


def _unique_lines(values: list[str]) -> list[str]:
    seen = set()
    unique = []
    for value in values:
        cleaned = value.strip()
        key = cleaned.lower()
        if cleaned and key not in seen:
            seen.add(key)
            unique.append(cleaned)
    return unique


def _bullet_list(values: list[str], fallback: str) -> str:
    return "\n".join(f"- {value}" for value in values) if values else f"- {fallback}"


def _subsection_list(label: str, values: list[str]) -> str:
    return f"### {label}\n\n{_bullet_list(values, 'Not specified.')}"


def _section_summary_or_na(contract: dict, section_key: str) -> str:
    section = contract.get(section_key, {})
    has_content = False
    for field_key, field in section.get("fields", {}).items():
        if field.get("type") == "list" and _list_values(contract, section_key, field_key):
            has_content = True
            break
        if field.get("type") != "list" and field.get("value", "").strip():
            has_content = True
            break
    return _section_summary(contract, section_key) if has_content else "Not specified or not applicable."


def _field_line(label: str, field: dict | None) -> str:
    value = (field or {}).get("value") or "Not specified."
    provenance = (field or {}).get("provenance", "unknown")
    return f"**{label}:** {value} ({provenance})"


def _list_block(label: str, field: dict | None) -> str:
    lines = [f"## {label}"]
    items = (field or {}).get("items") or []
    if not items:
        lines.append("- Not specified.")
    for item in items:
        provenance = item.get("provenance", "unknown")
        lines.append(f"- {item.get('text', '')} ({provenance})")
    return "\n".join(lines)


def _section_summary(contract: dict, section_key: str) -> str:
    section = contract.get(section_key, {})
    lines = []
    for field in section.get("fields", {}).values():
        if field.get("type") == "list":
            lines.append(_list_block(field.get("label", "Field"), field))
        else:
            lines.append(_field_line(field.get("label", "Field"), field))
    return "\n\n".join(lines) or "Not specified."


def _open_questions(contract: dict, findings: list[dict]) -> str:
    fields = contract.get("definition_of_done", {}).get("fields", {})
    questions = [item.get("text", "") for item in fields.get("open_questions", {}).get("items", [])]
    questions.extend(
        finding["title"] for finding in findings if finding["status"] == "open" and finding["severity"] in {"critical", "high"}
    )
    return "\n".join(f"- {question}" for question in questions) if questions else "- None recorded."


def _label_for_node(workflow: dict, node_id: str) -> str:
    node = next((item for item in workflow["nodes"] if item["id"] == node_id), None)
    return node["label"] if node else node_id


def _finding_to_dict(finding) -> dict:
    return {
        "id": finding.id,
        "category": finding.category,
        "severity": finding.severity,
        "title": finding.title,
        "explanation": finding.explanation,
        "evidence": finding.evidence,
        "related_contract_section": finding.related_contract_section,
        "related_workflow_node_id": finding.related_workflow_node_id,
        "recommendation": finding.recommendation,
        "status": finding.status,
        "resolution_note": finding.resolution_note,
    }
