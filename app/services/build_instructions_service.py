from __future__ import annotations

from app.extensions import db
from app.models import ExperienceContract, SynthesisItem, utcnow
from app.schemas import ContractSuggestion, ProviderFailure, SynthesisResult, dump_model
from app.services.contract_service import (
    ensure_contract_shape,
    list_item,
    merge_contract_suggestions,
)
from app.services.prompt_service import get_prompt
from app.services.providers import DeterministicDemoProvider, get_provider

# Retain the existing model for exports, health checks, and older projects. Only
# records owned by this automatic process are replaced on subsequent generations.
ANALYSIS_LOCATOR = "automatic_background_analysis"
LIST_DESTINATIONS = {
    "tasks": ("implementation_plan", "implementation_steps"),
    "requirements": ("build_target", "core_features"),
    "constraints": ("product_intent", "known_constraints"),
    "risks": ("product_intent", "risks"),
    "assumptions": ("product_intent", "assumptions"),
    "integrations": ("build_target", "integrations"),
    "data_needs": ("build_target", "data_entities"),
    "open_questions": ("definition_of_done", "open_questions"),
}


def _generate(task: str, text: str, model: type) -> tuple:
    provider = get_provider()
    try:
        result = provider.generate_structured(
            task_name=task,
            system_prompt=get_prompt(task),
            user_prompt=text,
            response_model=model,
        )
        return result, provider.name, ""
    except ProviderFailure:
        fallback = DeterministicDemoProvider()
        result = fallback.generate_structured(
            task_name=task,
            system_prompt=get_prompt(task),
            user_prompt=text,
            response_model=model,
        )
        return result, fallback.name, "The local model was unavailable or returned an invalid draft. The built-in draft helper was used instead."


def generate_build_instructions(contract: ExperienceContract) -> dict:
    """Analyze saved background and merge an editable draft in one transaction.

    The caller commits. Existing user edits and legacy included/excluded records
    survive generation. Legacy records can also support projects whose original
    background documents are no longer available.
    """
    project = contract.project
    sources = [
        (source, (source.edited_text or source.extracted_text or "").strip())
        for source in project.source_documents
        if (source.edited_text or source.extracted_text or "").strip()
    ]
    legacy_items = [
        item for item in project.synthesis_items
        if item.source_locator != ANALYSIS_LOCATOR
        and item.inclusion_status == "included" and item.text.strip()
    ]
    if not sources and not legacy_items:
        raise ValueError("Add and save Background Information before generating Build Instructions.")

    items = list(legacy_items)
    providers, notices = [], []
    # Analyze every saved document, retaining source identity and full text.
    for source, text in sources:
        result, provider, notice = _generate("intake_synthesis", text, SynthesisResult)
        providers.append(provider)
        notices.append(notice)
        for payload in dump_model(result)["items"]:
            items.append(SynthesisItem(
                category=payload["category"],
                text=payload["text"],
                source_document_id=source.id,
                source_locator=ANALYSIS_LOCATOR,
                is_inference=payload["is_inference"],
                confidence=payload["confidence"],
                inclusion_status="included",
            ))

    context = "\n\n".join(
        ["Current saved project decisions (take precedence over earlier background):\n"
         f"Original description: {project.description}\nProduct type: {project.workflow_name}\n"
         f"Audience: {project.target_user}\nDesired outcome: {project.desired_outcome}"]
        + [f"Background Information — {source.title}:\n{text}" for source, text in sources]
        + ["Analyzed background:\n" + "\n".join(
            f"{item.category}: {item.text}"
            + (" [Unconfirmed inference]" if item.is_inference else "")
            for item in items
        )]
    )
    result, provider, notice = _generate("contract_suggestions", context, ContractSuggestion)
    providers.append(provider)
    notices.append(notice)
    suggested = ensure_contract_shape(dump_model(result)["content_json"], "provider_suggested")

    # Keep extracted decisions and uncertainty visible even if the drafting
    # provider omits them. Merging below preserves manual edits and deduplicates.
    for item in items:
        destination = LIST_DESTINATIONS.get(item.category)
        if destination:
            section, field = destination
            suggested[section]["fields"][field]["items"].append(list_item(item.text))
    for category, field in [("users", "target_user"), ("goals", "user_goal")]:
        stated = [item.text for item in items if item.category == category and not item.is_inference]
        if stated:
            suggested["product_intent"]["fields"][field]["value"] = "\n".join(stated)

    contract.content_json = merge_contract_suggestions(contract.content_json or {}, suggested)
    contract.updated_at = utcnow()
    for item in list(project.synthesis_items):
        if item.source_locator == ANALYSIS_LOCATOR:
            project.synthesis_items.remove(item)
    for item in items[len(legacy_items):]:
        project.synthesis_items.append(item)
    db.session.flush()
    return {
        "providers": list(dict.fromkeys(providers)),
        "notice": " ".join(dict.fromkeys(notice for notice in notices if notice)),
    }
