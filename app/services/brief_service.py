from __future__ import annotations

import copy
import hashlib
import json

from app.models import Project, utcnow
from app.services.contract_service import ensure_contract_shape, list_item

# These are views of existing fields, not new storage. Shared fields use the
# same key in every module and in the full Build Instructions editor.
BRIEF_MODULES = {
    "original_idea": ("Original idea", [
        "project.description", "build_target.artifact_type",
        "product_intent.target_user", "product_intent.desired_outcome",
    ]),
    "product_foundation": ("Product foundation", [
        "build_target.artifact_type", "product_intent.problem_statement",
        "product_intent.business_objective", "product_intent.desired_outcome",
    ]),
    "audience": ("Audience and user outcomes", [
        "product_intent.target_user", "product_intent.user_goal",
        "product_intent.desired_outcome", "product_intent.success_measures",
    ]),
    "core_experience": ("Core experience and features", [
        "build_target.core_features", "build_target.primary_surfaces",
        "implementation_plan.routes_or_views", "implementation_plan.implementation_steps",
    ]),
    "data_integrations": ("Data and integrations", [
        "build_target.data_entities", "build_target.integrations", "build_target.auth_and_roles",
    ]),
    "constraints_risks": ("Constraints and risks", [
        "product_intent.known_constraints", "implementation_plan.out_of_scope",
        "product_intent.assumptions", "product_intent.risks", "definition_of_done.open_questions",
    ]),
    "acceptance": ("Acceptance criteria", [
        "definition_of_done.functional_acceptance_criteria",
        "definition_of_done.ux_acceptance_criteria", "implementation_plan.acceptance_tests",
        "build_target.nonfunctional_requirements", "implementation_plan.ai_builder_instructions",
    ]),
}

# The pre-existing project summary columns are also read by Overview, health,
# quality checks, and exports. Keep those mirrors coherent when a shared field
# is explicitly edited; never create a second contract or new field location.
PROJECT_MIRRORS = {
    "build_target.artifact_type": ("workflow_name", 160),
    "product_intent.target_user": ("target_user", 240),
    "product_intent.desired_outcome": ("desired_outcome", None),
}


class BriefConflict(ValueError):
    pass


def brief_module(project: Project, key: str) -> dict:
    title, keys = BRIEF_MODULES[key]
    contract = ensure_contract_shape(project.active_contract.content_json if project.active_contract else {})
    fields = []
    for field_key in keys:
        if field_key == "project.description":
            field = {"label": "Original description", "type": "text", "value": project.description, "provenance": "user_written"}
        else:
            section, name = field_key.split(".")
            field = copy.deepcopy(contract[section]["fields"][name])
            if field_key in PROJECT_MIRRORS:
                value = getattr(project, PROJECT_MIRRORS[field_key][0])
                if value and not (field_key == "build_target.artifact_type" and value == "Build plan"):
                    field["value"] = value
        field["key"] = field_key
        if field_key in PROJECT_MIRRORS and PROJECT_MIRRORS[field_key][1]:
            field["maxlength"] = PROJECT_MIRRORS[field_key][1]
        value = field.get("items", []) if field["type"] == "list" else field.get("value", "")
        field["state"] = "missing" if not value else "user_confirmed" if field["provenance"] == "user_written" else "ai_draft"
        field["state_label"] = {"missing": "Missing", "user_confirmed": "User confirmed", "ai_draft": "AI draft"}[field["state"]]
        fields.append(field)
    revision = hashlib.sha256(json.dumps(
        {"contract": project.active_contract.id if project.active_contract else None, "fields": fields},
        sort_keys=True,
    ).encode()).hexdigest()
    return {"key": key, "title": title, "fields": fields, "revision": revision}


def brief_modules(project: Project) -> list[dict]:
    return [brief_module(project, key) for key in BRIEF_MODULES]


def save_brief_module(project: Project, key: str, payload: dict) -> None:
    if not isinstance(payload, dict) or not isinstance(payload.get("fields"), dict):
        raise ValueError("Provide the fields to save.")
    module = brief_module(project, key)
    if payload.get("revision") != module["revision"]:
        raise BriefConflict("This section changed since you opened it. Close and reopen it to load the latest values before saving.")
    if not project.active_contract:
        raise ValueError("Build Instructions are unavailable for this agent.")
    definitions = {field["key"]: field for field in module["fields"]}
    if not payload["fields"].keys() <= definitions.keys():
        raise ValueError("Only fields in this section can be saved.")
    content = ensure_contract_shape(project.active_contract.content_json)
    project_changes = {}
    for field_key, value in payload["fields"].items():
        definition = definitions[field_key]
        if definition["type"] == "text":
            if not isinstance(value, str):
                raise ValueError(f"{definition['label']} must be text.")
            value = value.strip()
            if definition.get("maxlength") and len(value) > definition["maxlength"]:
                raise ValueError(f"{definition['label']} must be {definition['maxlength']} characters or fewer.")
            if field_key == "project.description":
                project_changes["description"] = value
                continue
            section, name = field_key.split(".")
            content[section]["fields"][name]["value"] = value
            if field_key in PROJECT_MIRRORS:
                project_changes[PROJECT_MIRRORS[field_key][0]] = value
        else:
            if not isinstance(value, list):
                raise ValueError(f"{definition['label']} must be a list.")
            section, name = field_key.split(".")
            old_items = {item["id"]: item for item in content[section]["fields"][name]["items"]}
            items, used_ids = [], set()
            for item in value:
                if not isinstance(item, dict) or not isinstance(item.get("text"), str):
                    raise ValueError(f"Each item in {definition['label']} must contain text.")
                item_id = item.get("id")
                if item_id is not None and (not isinstance(item_id, str) or item_id not in old_items or item_id in used_ids):
                    raise ValueError("A list item is no longer available. Reopen the section and try again.")
                text = item["text"].strip()
                if item_id:
                    used_ids.add(item_id)
                if not text:
                    continue
                if item_id:
                    saved = copy.deepcopy(old_items[item_id])
                    if saved["text"] != text:
                        saved.update(text=text, provenance="user_written")
                else:
                    saved = list_item(text, "user_written")
                items.append(saved)
            content[section]["fields"][name]["items"] = items
        content[section]["fields"][name]["provenance"] = "user_written"
    # Validate everything before applying any changes; the route commits once.
    for name, value in project_changes.items():
        setattr(project, name, value)
    project.active_contract.content_json = content
    project.active_contract.updated_at = utcnow()


def sync_project_summary(project: Project, old_content: dict, content: dict) -> None:
    """Keep existing summary columns in sync with full-instruction edits too."""
    before, after = ensure_contract_shape(old_content), ensure_contract_shape(content)
    for key, (attribute, _limit) in PROJECT_MIRRORS.items():
        section, name = key.split(".")
        value = after[section]["fields"][name]["value"]
        if value != before[section]["fields"][name]["value"]:
            setattr(project, attribute, value)
