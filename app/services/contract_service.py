from __future__ import annotations

import copy
from collections.abc import Mapping
from uuid import uuid4

from app.services.display_service import current_ui_copy

CONTRACT_BLUEPRINT = {
    "product_intent": {
        "title": "Product intent",
        "fields": {
            "problem_statement": {"label": "Problem statement", "type": "text"},
            "target_user": {"label": "Target user", "type": "text"},
            "user_goal": {"label": "User goal", "type": "text"},
            "desired_outcome": {"label": "Desired outcome", "type": "text"},
            "business_objective": {"label": "Business objective", "type": "text"},
            "success_measures": {"label": "Success measures", "type": "list"},
            "known_constraints": {"label": "Known constraints", "type": "list"},
            "risks": {"label": "Risks", "type": "list"},
            "assumptions": {"label": "Unresolved assumptions", "type": "list"},
        },
    },
    "build_target": {
        "title": "Build target",
        "fields": {
            "artifact_type": {"label": "Build type", "type": "text"},
            "target_platform": {"label": "Target platform or stack", "type": "text"},
            "primary_surfaces": {"label": "Screens, pages, or surfaces", "type": "list"},
            "core_features": {"label": "Core features to build", "type": "list"},
            "data_entities": {"label": "Data models or content types", "type": "list"},
            "integrations": {"label": "Integrations, tools, or APIs", "type": "list"},
            "auth_and_roles": {"label": "Authentication, permissions, and roles", "type": "list"},
            "deployment_environment": {"label": "Deployment environment", "type": "text"},
            "environment_variables": {"label": "Environment variables or secrets", "type": "list"},
            "nonfunctional_requirements": {"label": "Performance, accessibility, and quality requirements", "type": "list"},
        },
    },
    "implementation_plan": {
        "title": "Implementation plan",
        "fields": {
            "implementation_steps": {"label": "Implementation steps", "type": "list"},
            "routes_or_views": {"label": "Routes, views, or modules", "type": "list"},
            "data_flow": {"label": "Data flow", "type": "list"},
            "acceptance_tests": {"label": "Build acceptance tests", "type": "list"},
            "out_of_scope": {"label": "Out of scope", "type": "list"},
            "ai_builder_instructions": {"label": "Instructions for the AI builder", "type": "text"},
        },
    },
    "responsibility_model": {
        "title": "Responsibility model",
        "fields": {
            "agent_responsibilities": {"label": "AI/agent responsibilities when applicable", "type": "list"},
            "human_responsibilities": {"label": "Human responsibilities", "type": "list"},
            "shared_responsibilities": {"label": "Shared responsibilities", "type": "list"},
            "prohibited_agent_actions": {"label": "Prohibited AI/agent actions", "type": "list"},
        },
    },
    "autonomy_controls": {
        "title": "Autonomy controls",
        "fields": {
            "automatic_actions": {"label": "Actions that can happen automatically", "type": "list"},
            "review_actions": {"label": "Actions that require review", "type": "list"},
            "confirmation_actions": {
                "label": "Actions that require explicit confirmation",
                "type": "list",
            },
            "high_impact_actions": {"label": "Irreversible or high-impact actions", "type": "list"},
        },
    },
    "confidence_behavior": {
        "title": "Confidence behavior",
        "fields": {
            "high": {"label": "High confidence behavior", "type": "text"},
            "medium": {"label": "Medium confidence behavior", "type": "text"},
            "low": {"label": "Low confidence behavior", "type": "text"},
            "unknown": {"label": "Unknown confidence behavior", "type": "text"},
            "ask_question_when": {"label": "When the AI/agent must ask a question", "type": "list"},
            "refuse_or_stop_when": {"label": "When the AI/agent must refuse or stop", "type": "list"},
            "supporting_evidence": {"label": "Supporting evidence to show", "type": "list"},
        },
    },
    "data_and_memory": {
        "title": "Data and memory",
        "fields": {
            "may_read": {"label": "Data the AI/agent may read", "type": "list"},
            "may_create_or_modify": {"label": "Data the AI/agent may create or modify", "type": "list"},
            "must_never_access": {"label": "Data it must never access", "type": "list"},
            "session_memory": {"label": "Information retained during a session", "type": "list"},
            "cross_session_memory": {"label": "Information retained between sessions", "type": "list"},
            "memory_controls": {"label": "User controls for remembered information", "type": "list"},
        },
    },
    "transparency_and_trust": {
        "title": "Transparency and trust",
        "fields": {
            "activity_history": {"label": "Activity history", "type": "text"},
            "source_display": {"label": "Source or evidence display", "type": "text"},
            "explanation_requirements": {"label": "Explanation requirements", "type": "list"},
            "generated_content_labeling": {"label": "Generated-content labeling", "type": "text"},
            "change_preview_requirements": {"label": "Change preview requirements", "type": "list"},
            "undo_recovery_expectations": {"label": "Undo and recovery expectations", "type": "list"},
        },
    },
    "escalation_and_recovery": {
        "title": "Escalation and recovery",
        "fields": {
            "missing_information": {"label": "Missing information", "type": "text"},
            "conflicting_instructions": {"label": "Conflicting instructions", "type": "text"},
            "tool_failure": {"label": "Tool failure", "type": "text"},
            "partial_completion": {"label": "Partial completion", "type": "text"},
            "incorrect_action": {"label": "Incorrect action", "type": "text"},
            "safe_stopping_conditions": {"label": "Safe stopping conditions", "type": "list"},
        },
    },
    "definition_of_done": {
        "title": "Definition of done",
        "fields": {
            "ux_acceptance_criteria": {"label": "UX acceptance criteria", "type": "list"},
            "functional_acceptance_criteria": {
                "label": "Functional acceptance criteria",
                "type": "list",
            },
            "open_questions": {"label": "Open questions", "type": "list"},
        },
    },
}


def _blank_field(field: dict, provenance: str) -> dict:
    if field["type"] == "list":
        return {
            "label": field["label"],
            "type": "list",
            "items": [],
            "provenance": provenance,
        }
    return {
        "label": field["label"],
        "type": "text",
        "value": "",
        "provenance": provenance,
    }


def blank_contract_content(provenance: str = "user_written") -> dict:
    content = {}
    for section_key, section in CONTRACT_BLUEPRINT.items():
        fields = {}
        for field_key, field in section["fields"].items():
            fields[field_key] = _blank_field(field, provenance)
        content[section_key] = {"title": section["title"], "fields": fields}
    return content


def ensure_contract_shape(content: dict | None, provenance: str = "user_written") -> dict:
    original = copy.deepcopy(content) if isinstance(content, Mapping) else {}
    shaped = {}
    for section_key, section in CONTRACT_BLUEPRINT.items():
        shaped[section_key] = {"title": section["title"], "fields": {}}
        fields = shaped[section_key].setdefault("fields", {})
        old_section = original.get(section_key, {})
        old_fields = old_section.get("fields", {}) if isinstance(old_section, Mapping) else {}
        if not isinstance(old_fields, Mapping):
            old_fields = {}
        for field_key, field in section["fields"].items():
            if field_key not in old_fields:
                fields[field_key] = _blank_field(field, provenance)
                continue
            candidate = old_fields[field_key]
            old_field = copy.deepcopy(candidate) if isinstance(candidate, Mapping) else {}
            fields[field_key] = _blank_field(field, provenance)
            fields[field_key]["label"] = old_field.get("label") or field["label"]
            fields[field_key]["type"] = field["type"]
            fields[field_key]["provenance"] = old_field.get("provenance") or provenance
            if field["type"] == "list":
                old_items = old_field.get("items", [])
                if not isinstance(old_items, list):
                    old_items = []
                fields[field_key]["items"] = [
                    {
                        "id": item.get("id") or str(uuid4()),
                        "text": current_ui_copy(item.get("text", "")),
                        "provenance": item.get("provenance") or provenance,
                    }
                    for item in old_items
                    if isinstance(item, Mapping)
                    and isinstance(item.get("text"), str)
                    and item["text"].strip()
                ]
            else:
                value = old_field.get("value", "")
                fields[field_key]["value"] = current_ui_copy(value) if isinstance(value, str) else ""
    return shaped


def list_item(text: str, provenance: str = "provider_suggested") -> dict:
    return {
        "id": str(uuid4()),
        "text": text,
        "provenance": provenance,
    }


def merge_contract_suggestions(existing: dict, suggested: dict) -> dict:
    content = ensure_contract_shape(existing or blank_contract_content())
    if not isinstance(suggested, Mapping):
        return content
    for section_key, section in suggested.items():
        if section_key not in content or not isinstance(section, Mapping):
            continue
        suggested_fields = section.get("fields", {})
        if not isinstance(suggested_fields, Mapping):
            continue
        for field_key, payload in suggested_fields.items():
            if field_key not in content[section_key]["fields"] or not isinstance(payload, Mapping):
                continue
            target = content[section_key]["fields"][field_key]
            if target["type"] == "list":
                existing_texts = {item.get("text", "").strip().lower() for item in target.get("items", [])}
                suggested_items = payload.get("items", [])
                if not isinstance(suggested_items, list):
                    continue
                for item in suggested_items:
                    if not isinstance(item, Mapping):
                        continue
                    raw_text = item.get("text", "")
                    text = raw_text.strip() if isinstance(raw_text, str) else ""
                    if text and text.lower() not in existing_texts:
                        target.setdefault("items", []).append(list_item(text, "provider_suggested"))
                        existing_texts.add(text.lower())
            else:
                current = target.get("value", "").strip()
                raw_value = payload.get("value", "")
                value = raw_value.strip() if isinstance(raw_value, str) else ""
                if value and not current:
                    target["value"] = value
                    target["provenance"] = "provider_suggested"
    return content
