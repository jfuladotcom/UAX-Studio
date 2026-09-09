from __future__ import annotations

import json
import re
from typing import Protocol, TypeVar

import requests
from flask import current_app
from pydantic import BaseModel, ValidationError

from app.schemas import (
    ContractSuggestion,
    ProviderFailure,
    ReviewResult,
    SynthesisResult,
    validate_model,
)
from app.services.contract_service import blank_contract_content, list_item
from app.services.prompt_service import build_repair_prompt, build_structured_output_prompt
from app.services.settings import load_settings

T = TypeVar("T", bound=BaseModel)


OLLAMA_PROVIDER_PREFIX = "ollama::"
OLLAMA_DISCOVERY_TIMEOUT = 2


def _coerce_timeout(value: object, fallback: int = 20) -> int:
    try:
        timeout = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(1, min(timeout, 120))


def _infer_artifact_type(text: str) -> str:
    lower = text.lower()
    if any(word in lower for word in ["website", "site", "landing page", "portfolio"]):
        return "Website"
    if any(word in lower for word in ["agent", "assistant", "copilot", "chatbot"]):
        return "AI agent"
    if any(word in lower for word in ["automation", "workflow", "zap"]):
        return "Automation workflow"
    if any(word in lower for word in ["dashboard", "portal", "tool", "crm", "app", "application"]):
        return "Application"
    return "Build project"


class AIProvider(Protocol):
    name: str

    def generate_structured(
        self,
        *,
        task_name: str,
        system_prompt: str,
        user_prompt: str,
        response_model: type[T],
    ) -> T:
        ...


class DeterministicDemoProvider:
    name = "deterministic"

    def generate_structured(
        self,
        *,
        task_name: str,
        system_prompt: str,
        user_prompt: str,
        response_model: type[T],
    ) -> T:
        if response_model is SynthesisResult or task_name == "intake_synthesis":
            data = self._synthesis(user_prompt)
        elif response_model is ContractSuggestion or task_name == "contract_suggestions":
            data = self._contract(user_prompt)
        elif response_model is ReviewResult or task_name.startswith("review_"):
            reviewer_type = task_name.replace("review_", "") or "interaction_architect"
            data = self._review(reviewer_type)
        else:
            data = {}
        return validate_model(response_model, data)

    def _synthesis(self, text: str) -> dict:
        lower = text.lower()
        is_gallery = "artist" in lower or "artwork" in lower or "galleryflow" in lower
        if is_gallery:
            items = [
                ("users", "Submission coordinators need one reliable place to inspect artist records.", "Source: demo brief", False, "high"),
                ("users", "Review staff verify corrections, outbound messages, and final checklist exports.", "Inference", True, "medium"),
                ("goals", "Turn inconsistent submission material into a normalized staff-reviewed artwork record.", "Source: demo brief", False, "high"),
                ("tasks", "Extract artist identity, contact details, biography, artwork dimensions, medium, price, and attachments.", "Source: demo brief", False, "high"),
                ("tasks", "Draft clarification requests when required information is missing or conflicting.", "Source: demo brief", False, "high"),
                ("pain_points", "Staff currently copy information across forms, email attachments, and spreadsheets by hand.", "Source: demo brief", False, "high"),
                ("business_objectives", "Reduce coordination time while preserving curatorial review and artist trust.", "Inference", True, "medium"),
                ("requirements", "The agent must preview normalized records before they are committed.", "Source: demo brief", False, "high"),
                ("requirements", "Outgoing clarification email drafts require staff confirmation before sending.", "Source: demo brief", False, "high"),
                ("constraints", "The agent must not invent missing dimensions, prices, materials, or contact information.", "Source: demo brief", False, "high"),
                ("assumptions", "Submitted files are available locally during the coordination session.", "Inference", True, "medium"),
                ("risks", "Low-confidence extraction may be mistaken for verified artist-provided information.", "Inference", True, "medium"),
                ("open_questions", "Who owns final review when a staff reviewer is unavailable?", "Inference", True, "medium"),
            ]
        else:
            trimmed = " ".join(text.split())[:240]
            subject = trimmed or "the proposed build"
            items = [
                ("users", "Primary users need the target product to match the workflow described in the brief.", "Inference", True, "medium"),
                ("goals", f"Create an AI-ready build brief for {subject}.", "Inference", True, "medium"),
                ("tasks", "Identify the user flow, screens or surfaces, features, data, integrations, and acceptance checks needed for implementation.", "Inference", True, "medium"),
                ("requirements", "The exported Markdown should tell an AI builder what to build, what to avoid, and how success will be verified.", "Inference", True, "medium"),
                ("requirements", "Keep any AI or agent behavior explicit, reviewable, and tied to the user's stated outcome.", "Inference", True, "medium"),
                ("constraints", "The initial brief may omit platform, data model, integration, auth, or deployment decisions.", "Inference", True, "medium"),
                ("assumptions", "The proposed scope and implementation choices still need user review.", "Inference", True, "medium"),
                ("risks", "A vague build brief can cause an AI builder to implement the wrong product or invent missing requirements.", "Inference", True, "medium"),
                ("open_questions", "What build type, platform, data model, integrations, and launch constraints should be locked before implementation?", "Inference", True, "medium"),
            ]
        # Preserve explicit facts throughout every document, including material
        # after the short summary used by the built-in draft helper.
        categories = {
            "users": r"\b(users?|audience|customers?|staff)\b",
            "goals": r"\b(goals?|outcomes?|aims?)\b",
            "requirements": r"\b(requirements?|features?|must|needs?|should|shall)\b",
            "constraints": r"\b(constraints?|limits?|must not|cannot|budget|deadline|only)\b",
            "risks": r"\b(risks?|failure|conflict)\b",
            "assumptions": r"\b(assumptions?|assume|assuming)\b",
            "integrations": r"\b(integrations?|integrate|api|webhook|connect to)\b",
            "data_needs": r"\b(data|database|records?|store|storage|entities)\b",
        }
        for number, sentence in enumerate(re.split(r"\n+|(?<=[.!?])\s+", text), start=1):
            sentence = sentence.strip(" \t-*#")
            if not sentence:
                continue
            if "?" in sentence or re.search(r"\b(open question|unanswered|unknown|tbd)\b", sentence, re.I):
                matches = ["open_questions"]
            elif re.search(categories["assumptions"], sentence, re.I):
                matches = ["assumptions"]
            elif re.search(categories["risks"], sentence, re.I):
                matches = ["risks"]
            else:
                matches = [key for key, pattern in categories.items() if re.search(pattern, sentence, re.I)]
            for category in matches:
                items.append((category, sentence, f"Source: statement {number}", category == "assumptions", "high"))
        return {
            "label": "Draft suggestions from the built-in helper",
            "items": [
                {
                    "category": category,
                    "text": text_value,
                    "source_reference": source,
                    "is_inference": inference,
                    "confidence": confidence,
                }
                for category, text_value, source, inference, confidence in items
            ],
        }

    def _contract(self, context: str) -> dict:
        lower = context.lower()
        is_gallery = "artist" in lower or "artwork" in lower or "galleryflow" in lower
        if not is_gallery:
            return self._generic_contract(context)

        content = blank_contract_content("provider_suggested")

        def set_text(section: str, field: str, value: str):
            content[section]["fields"][field]["value"] = value

        def set_list(section: str, field: str, values: list[str]):
            content[section]["fields"][field]["items"] = [list_item(value) for value in values]

        set_text(
            "product_intent",
            "problem_statement",
            "Submission staff need to turn inconsistent artist materials into a trustworthy, reviewable record without losing source context.",
        )
        set_text("product_intent", "target_user", "Arts-organization submission coordinator")
        set_text("product_intent", "user_goal", "Prepare a complete artist submission package for team review.")
        set_text(
            "product_intent",
            "desired_outcome",
            "A normalized artist and artwork record, clarification draft when needed, and final checklist ready for review.",
        )
        set_text("product_intent", "business_objective", "Reduce manual coordination time while preserving staff oversight.")
        set_list(
            "product_intent",
            "success_measures",
            [
                "Staff can trace every normalized field back to source material.",
                "No outbound communication or published record occurs without staff confirmation.",
                "Missing or conflicting information is surfaced before export.",
                "AI_BUILD_BRIEF.md describes the GalleryFlow product to build, not UAX Studio itself.",
            ],
        )
        set_list(
            "product_intent",
            "known_constraints",
            [
                "Source documents can be incomplete or contradictory.",
                "Submitted artist wording must not be silently rewritten.",
                "Original source files must remain preserved.",
            ],
        )
        set_text("build_target", "artifact_type", "Internal workflow application with assisted review")
        set_text("build_target", "target_platform", "Local-first web app or private internal tool")
        set_list(
            "build_target",
            "primary_surfaces",
            [
                "Submission intake and source review",
                "Normalized artist and artwork record preview",
                "Clarification request drafting",
                "Staff review checklist",
                "Export or handoff package",
            ],
        )
        set_list(
            "build_target",
            "core_features",
            [
                "Import submitted artist materials from supported source files.",
                "Extract artist, artwork, contact, and exhibition details with source references.",
                "Flag missing, conflicting, or low-confidence information.",
                "Let staff review, edit, or send back every normalized record and outbound draft.",
                "Generate a final reviewed checklist and implementation handoff package.",
            ],
        )
        set_list(
            "build_target",
            "data_entities",
            ["Artist", "Artwork", "Source document", "Clarification request", "Review decision", "Checklist item"],
        )
        set_list(
            "build_target",
            "integrations",
            ["Local file parsing", "Optional local AI provider", "Export bundle generation"],
        )
        set_list(
            "build_target",
            "auth_and_roles",
            ["Submission coordinator can edit and finalize records.", "Review staff can inspect findings and resolve exceptions."],
        )
        set_text("build_target", "deployment_environment", "Local desktop or private internal web deployment")
        set_list(
            "build_target",
            "environment_variables",
            ["Optional local AI provider URL and model name", "Local upload and export directories"],
        )
        set_list(
            "build_target",
            "nonfunctional_requirements",
            ["Preserve source traceability", "Support keyboard-accessible review controls", "Never expose unselected local files"],
        )
        set_list(
            "implementation_plan",
            "implementation_steps",
            [
                "Build the submission intake and source-inspection flow.",
                "Implement editable extraction and confidence labeling.",
                "Add review, revision, recovery, and final checklist states.",
                "Package the reviewed output for handoff.",
            ],
        )
        set_list(
            "implementation_plan",
            "routes_or_views",
            ["Submissions dashboard", "Source detail", "Normalized record review", "Review checklist", "Export view"],
        )
        set_list(
            "implementation_plan",
            "data_flow",
            [
                "Source files become extracted text with provenance.",
                "Extracted fields become editable normalized records.",
                "Staff decisions update the reviewed checklist and export package.",
            ],
        )
        set_list(
            "implementation_plan",
            "acceptance_tests",
            [
                "A complete submission reaches final checklist export.",
                "A missing email pauses for clarification review.",
                "Conflicting artwork dimensions are shown before finalizing.",
            ],
        )
        set_list(
            "implementation_plan",
            "out_of_scope",
            ["Automatic publishing without confirmation", "Sending external email without staff confirmation"],
        )
        set_text(
            "implementation_plan",
            "ai_builder_instructions",
            "Build GalleryFlow itself from this brief. Do not build UAX Studio unless explicitly requested.",
        )
        set_list(
            "responsibility_model",
            "agent_responsibilities",
            [
                "Extract and normalize artist and artwork information.",
                "Identify missing, conflicting, and low-confidence fields.",
                "Draft clarification requests and checklist entries for review.",
                "Prepare a preview of the normalized record.",
            ],
        )
        set_list(
            "responsibility_model",
            "human_responsibilities",
            [
                "Review normalized identity, corrections, email drafts, final records, and checklist exports.",
                "Resolve conflicts that require curatorial judgment.",
                "Send back or edit any provider-suggested content.",
            ],
        )
        set_list(
            "responsibility_model",
            "shared_responsibilities",
            [
                "Maintain an auditable record of decisions and evidence.",
                "Keep artist-provided materials visible when making corrections.",
            ],
        )
        set_list(
            "responsibility_model",
            "prohibited_agent_actions",
            [
                "Send email without explicit staff confirmation.",
                "Invent missing dimensions, prices, materials, or contact information.",
                "Publish or delete records without staff confirmation.",
                "Rewrite an artist biography silently.",
            ],
        )
        set_list(
            "autonomy_controls",
            "automatic_actions",
            [
                "Parse supported uploaded files.",
                "Suggest normalized fields with confidence labels.",
                "Flag missing or conflicting data.",
            ],
        )
        set_list(
            "autonomy_controls",
            "review_actions",
            ["Suggested field corrections", "Checklist entry proposals", "Biography edits"],
        )
        set_list(
            "autonomy_controls",
            "confirmation_actions",
            [
                "Outgoing clarification request",
                "Completed artwork record",
                "Final checklist export",
            ],
        )
        set_list(
            "autonomy_controls",
            "high_impact_actions",
            ["Publishing records", "Deleting source material", "Sending external communication"],
        )
        set_text("confidence_behavior", "high", "Proceed to preview while showing source evidence.")
        set_text("confidence_behavior", "medium", "Proceed only with visible uncertainty and staff review.")
        set_text("confidence_behavior", "low", "Ask a clarifying question or route to staff review before continuing.")
        set_text("confidence_behavior", "unknown", "Stop automation and request human interpretation.")
        set_list(
            "confidence_behavior",
            "ask_question_when",
            ["Required contact details are missing", "Two sources conflict", "Extraction confidence is low"],
        )
        set_list(
            "confidence_behavior",
            "refuse_or_stop_when",
            ["Requested action would invent missing artist data", "Staff review is unavailable for a high-impact action"],
        )
        set_list(
            "confidence_behavior",
            "supporting_evidence",
            ["Source document name", "Field-level confidence", "Original submitted text", "Change preview"],
        )
        set_list(
            "data_and_memory",
            "may_read",
            ["Uploaded forms", "Email attachment text", "Submitted spreadsheets", "Staff notes"],
        )
        set_list(
            "data_and_memory",
            "may_create_or_modify",
            ["Draft normalized record", "Draft clarification request", "Internal checklist"],
        )
        set_list(
            "data_and_memory",
            "must_never_access",
            ["Unselected local files", "Private staff documents outside the project", "Unselected source material"],
        )
        set_list("data_and_memory", "session_memory", ["Current submission context", "Staff decisions in the run"])
        set_list("data_and_memory", "cross_session_memory", ["Current contract and workflow decisions"])
        set_list("data_and_memory", "memory_controls", ["View, edit, archive, and permanently delete project data"])
        set_text("transparency_and_trust", "activity_history", "Show extraction, review, revision, and export events.")
        set_text("transparency_and_trust", "source_display", "Display source references next to extracted and normalized fields.")
        set_list(
            "transparency_and_trust",
            "explanation_requirements",
            ["Explain why a field needs review", "Show confidence and evidence for every correction"],
        )
        set_text("transparency_and_trust", "generated_content_labeling", "Label provider output as demo-assisted suggestions.")
        set_list(
            "transparency_and_trust",
            "change_preview_requirements",
            ["Before/after biography diff", "Field-level normalized record preview", "Checklist preview"],
        )
        set_list(
            "transparency_and_trust",
            "undo_recovery_expectations",
            ["Undo draft changes before finalizing", "Restore archived projects", "Retain original source text"],
        )
        set_text("escalation_and_recovery", "missing_information", "Draft a clarification request and pause for staff review.")
        set_text("escalation_and_recovery", "conflicting_instructions", "Show the conflicting sources and ask staff to choose.")
        set_text("escalation_and_recovery", "tool_failure", "Record the failure, preserve available source text, and offer manual entry.")
        set_text("escalation_and_recovery", "partial_completion", "Mark completed fields and explain remaining blockers.")
        set_text("escalation_and_recovery", "incorrect_action", "Stop, show activity history, and require staff correction.")
        set_list(
            "escalation_and_recovery",
            "safe_stopping_conditions",
            ["Staff review unavailable", "Source parsing failed", "Destructive action requested without undo"],
        )
        set_list(
            "definition_of_done",
            "ux_acceptance_criteria",
            [
                "Staff can inspect evidence before finalizing each review point.",
                "Every pause state has a clear next action.",
                "Sent-back changes preserve the previous value.",
            ],
        )
        set_list(
            "definition_of_done",
            "functional_acceptance_criteria",
            [
                "Files extract into editable project sources.",
                "Saved background information informs Build Instructions.",
                "Workflow details cover review points and failure paths.",
                "Exports include Markdown, JSON, Mermaid, manifest, and AI_BUILD_BRIEF.md.",
            ],
        )
        set_list(
            "definition_of_done",
            "open_questions",
            ["Who owns escalation when the assigned submission coordinator is unavailable?"],
        )
        return {"label": "Draft build instructions from the built-in helper", "content_json": content}

    def _generic_contract(self, context: str) -> dict:
        content = blank_contract_content("provider_suggested")
        subject = " ".join(context.split())[:220] or "the proposed build"
        artifact_type = _infer_artifact_type(subject)

        def set_text(section: str, field: str, value: str):
            content[section]["fields"][field]["value"] = value

        def set_list(section: str, field: str, values: list[str]):
            content[section]["fields"][field]["items"] = [list_item(value) for value in values]

        set_text(
            "product_intent",
            "problem_statement",
            f"Users need a clear, buildable product specification for {subject}.",
        )
        set_text("product_intent", "target_user", "Primary user or operator")
        set_text("product_intent", "user_goal", "Use the finished product to complete the workflow described in the brief.")
        set_text(
            "product_intent",
            "desired_outcome",
            "An AI-ready Markdown build brief that can guide implementation of the target product.",
        )
        set_text(
            "product_intent",
            "business_objective",
            "Turn product intent into enough implementation detail for a faster, better-scoped build.",
        )
        set_list(
            "product_intent",
            "success_measures",
            [
                "The build brief names the target artifact, users, core features, data, and acceptance checks.",
                "Workflow steps make the expected user journey and handoff points clear.",
                "Open questions and out-of-scope items are visible before implementation begins.",
            ],
        )
        set_list(
            "product_intent",
            "known_constraints",
            [
                "The initial brief may be incomplete.",
                "Platform, integrations, data model, and deployment choices may need confirmation.",
                "Local provider quality depends on the selected model when AI suggestions are enabled.",
            ],
        )
        set_text("build_target", "artifact_type", artifact_type)
        set_text("build_target", "target_platform", "Confirm the preferred framework, host, and runtime before implementation.")
        set_list(
            "build_target",
            "primary_surfaces",
            [
                "Primary user entry point",
                "Main workflow or content surface",
                "Review, settings, or output surface",
            ],
        )
        set_list(
            "build_target",
            "core_features",
            [
                f"Implement the target {artifact_type.lower()} described by the brief.",
                "Support the primary user flow from intake/start through final outcome.",
                "Make important outputs editable or reviewable when the brief implies human judgment.",
                "Produce a clear final result, handoff, or published surface.",
            ],
        )
        set_list(
            "build_target",
            "data_entities",
            ["Primary user", "Project or workflow item", "Source/input record", "Generated or reviewed output"],
        )
        set_list(
            "build_target",
            "integrations",
            ["List required APIs, tools, model providers, or third-party services before coding."],
        )
        set_list(
            "build_target",
            "auth_and_roles",
            ["Define public, signed-in, admin, reviewer, or agent roles if the product needs them."],
        )
        set_text("build_target", "deployment_environment", "Not specified; choose a local or production target that matches the user's brief.")
        set_list(
            "build_target",
            "environment_variables",
            ["Record API keys, model names, database URLs, and service endpoints as placeholders only."],
        )
        set_list(
            "build_target",
            "nonfunctional_requirements",
            ["Responsive layout", "Accessible controls", "Clear empty and error states", "No hidden destructive actions"],
        )
        set_list(
            "implementation_plan",
            "implementation_steps",
            [
                "Confirm the build target and platform.",
                "Implement the primary surfaces and core user flow.",
                "Add data storage, integrations, and permissions required by the brief.",
                "Write acceptance checks for the most important workflow paths.",
            ],
        )
        set_list(
            "implementation_plan",
            "routes_or_views",
            ["Home or main workspace", "Primary workflow view", "Detail or editor view", "Settings or export/output view"],
        )
        set_list(
            "implementation_plan",
            "data_flow",
            [
                "User input or source material creates project state.",
                "Workflow steps transform that state into the intended output.",
                "The final surface, export, or handoff presents the reviewed result.",
            ],
        )
        set_list(
            "implementation_plan",
            "acceptance_tests",
            [
                "The happy path reaches the desired outcome.",
                "Missing required information produces a recoverable prompt or error state.",
                "The final output matches the user's reviewed build brief.",
            ],
        )
        set_list("implementation_plan", "out_of_scope", ["Do not invent unsupported integrations, secrets, or production actions."])
        set_text(
            "implementation_plan",
            "ai_builder_instructions",
            "Use this contract and workflow to build the target product described by the user. Do not implement UAX Studio itself unless the user explicitly asks for that.",
        )
        set_list(
            "responsibility_model",
            "agent_responsibilities",
            [
                "Summarize the build request and relevant context.",
                "Draft implementation details, workflow steps, and acceptance checks.",
                "Flag missing build information, uncertainty, and risks.",
                "Prepare reviewed build brief content for handoff.",
            ],
        )
        set_list(
            "responsibility_model",
            "human_responsibilities",
            [
                "Review, edit, or send back important build-scope decisions.",
                "Provide missing platform, data, integration, and deployment context.",
                "Own final scope decisions and high-impact product actions.",
            ],
        )
        set_list(
            "responsibility_model",
            "shared_responsibilities",
            [
                "Keep source context visible during decisions.",
                "Record why a build-scope decision was accepted or changed.",
            ],
        )
        set_list(
            "responsibility_model",
            "prohibited_agent_actions",
            [
                "Take irreversible action without confirmation.",
                "Invent missing facts or authority.",
                "Hide uncertainty from the user.",
                "Access data outside the project scope.",
            ],
        )
        set_list(
            "autonomy_controls",
            "automatic_actions",
            [
                "Summarize provided source material.",
                "Generate editable build brief suggestions.",
                "Label confidence and known blockers.",
            ],
        )
        set_list(
            "autonomy_controls",
            "review_actions",
            [
                "Build brief sections based on incomplete context.",
                "Drafts that change user-facing content.",
                "Decisions with medium confidence.",
            ],
        )
        set_list(
            "autonomy_controls",
            "confirmation_actions",
            [
                "External messages or submissions.",
                "Final build briefs used by another team or system.",
                "Any high-impact or hard-to-undo action.",
            ],
        )
        set_list(
            "autonomy_controls",
            "high_impact_actions",
            ["Sending, publishing, deleting, purchasing, committing, or changing official records"],
        )
        set_text("confidence_behavior", "high", "Proceed to the next draft step while keeping review available.")
        set_text("confidence_behavior", "medium", "Proceed only with visible uncertainty and a review checkpoint.")
        set_text("confidence_behavior", "low", "Ask a question or escalate to a human before continuing.")
        set_text("confidence_behavior", "unknown", "Stop automation and request human interpretation.")
        set_list(
            "confidence_behavior",
            "ask_question_when",
            ["Required context is missing", "Instructions conflict", "The next action is high impact"],
        )
        set_list(
            "confidence_behavior",
            "refuse_or_stop_when",
            ["The request would require invented facts", "Review is unavailable for a high-impact action"],
        )
        set_list(
            "confidence_behavior",
            "supporting_evidence",
            ["Original source text", "Confidence label", "Reason for build suggestion", "Open questions"],
        )
        set_list(
            "data_and_memory",
            "may_read",
            ["Source text and files added to the project", "Current workflow and contract decisions"],
        )
        set_list(
            "data_and_memory",
            "may_create_or_modify",
            ["Draft build brief content", "Workflow notes", "Implementation export files"],
        )
        set_list(
            "data_and_memory",
            "must_never_access",
            ["Unselected local files", "Secrets", "Private data outside the project"],
        )
        set_list("data_and_memory", "session_memory", ["Current request context", "Current draft decisions"])
        set_list("data_and_memory", "cross_session_memory", ["Current project state"])
        set_list("data_and_memory", "memory_controls", ["Review, edit, archive, and delete project data"])
        set_text("transparency_and_trust", "activity_history", "Show drafts, reviews, revisions, and exports.")
        set_text("transparency_and_trust", "source_display", "Keep source context near each build suggestion.")
        set_list(
            "transparency_and_trust",
            "explanation_requirements",
            ["Explain confidence", "Explain blockers", "Show what changed before finalizing"],
        )
        set_text("transparency_and_trust", "generated_content_labeling", "Label generated text as editable AI draft output.")
        set_list(
            "transparency_and_trust",
            "change_preview_requirements",
            ["Before/after text for edits", "Clear final handoff preview"],
        )
        set_list(
            "transparency_and_trust",
            "undo_recovery_expectations",
            ["Send draft output back for changes", "Return to manual handling", "Preserve previous reviewed state"],
        )
        set_text("escalation_and_recovery", "missing_information", "Ask the user for the missing detail before continuing.")
        set_text("escalation_and_recovery", "conflicting_instructions", "Show the conflict and ask the user to choose.")
        set_text("escalation_and_recovery", "tool_failure", "Record the failure and keep manual handling available.")
        set_text("escalation_and_recovery", "partial_completion", "Show what is complete and what remains unfinished.")
        set_text("escalation_and_recovery", "incorrect_action", "Stop, show the activity history, and require correction.")
        set_list(
            "escalation_and_recovery",
            "safe_stopping_conditions",
            ["Low confidence", "Missing required context", "High-impact action without confirmation"],
        )
        set_list(
            "definition_of_done",
            "ux_acceptance_criteria",
            [
                "The user can see and edit the draft before finalizing.",
                "Pause states show the next required action.",
                "Revision requests route to a safe manual path.",
            ],
        )
        set_list(
            "definition_of_done",
            "functional_acceptance_criteria",
            [
                "Saved background information guides the build draft.",
                "The build contract includes target artifact, features, surfaces, data, and acceptance checks.",
                "Export includes AI_BUILD_BRIEF.md, contract, workflow, and acceptance criteria.",
            ],
        )
        set_list("definition_of_done", "open_questions", ["Which platform, integrations, or deployment target should be locked before implementation?"])
        return {"label": "Draft build instructions from the built-in helper", "content_json": content}

    def _review(self, reviewer_type: str) -> dict:
        catalog = {
            "interaction_architect": [
                {
                    "category": "Interaction",
                    "severity": "medium",
                    "title": "Build brief needs visible unknowns",
                    "explanation": "A builder needs a concise summary of what is known, unknown, and still open before implementation starts.",
                    "evidence": "Missing-detail checks can route back to human clarification.",
                    "related_contract_section": "implementation_plan",
                    "recommendation": "Keep unresolved platform, feature, data, integration, and deployment decisions visible in the exported brief.",
                }
            ],
            "trust_safety_critic": [
                {
                    "category": "Trust and safety",
                    "severity": "high",
                    "title": "High-impact implementation choices need explicit scope",
                    "explanation": "Auth, payments, data deletion, external messaging, and production integrations can materially change the product risk profile.",
                    "evidence": "The build contract includes review controls, permissions, integrations, and out-of-scope sections.",
                    "related_contract_section": "build_target",
                    "recommendation": "Require explicit user confirmation before adding high-impact integrations or irreversible production actions.",
                }
            ],
            "accessibility_reviewer": [
                {
                    "category": "Accessibility",
                    "severity": "medium",
                    "title": "Accessibility expectations should be part of the build brief",
                    "explanation": "The exported Markdown should tell a builder which accessibility and responsive behavior the target product must support.",
                    "evidence": "Build target quality requirements are exported with the implementation plan.",
                    "related_contract_section": "build_target",
                    "recommendation": "Add keyboard, contrast, responsive layout, and error-state acceptance checks when they matter to the target product.",
                }
            ],
            "technical_feasibility_reviewer": [
                {
                    "category": "Technical feasibility",
                    "severity": "medium",
                    "title": "Implementation assumptions should be explicit",
                    "explanation": "An AI builder may invent stack, storage, deployment, or integration decisions if the brief leaves them blank.",
                    "evidence": "The build contract has target platform, integrations, data flow, and environment variable fields.",
                    "related_contract_section": "implementation_plan",
                    "recommendation": "Lock the stack, storage, deployment target, and required services before treating the spec as build-ready.",
                }
            ],
        }
        findings = catalog.get(reviewer_type, catalog["interaction_architect"])
        return {"reviewer_type": reviewer_type, "summary": f"{reviewer_type} completed deterministically.", "findings": findings}


class OllamaProvider:
    name = "ollama"

    def __init__(self, base_url: str, model: str, timeout: int = 20):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def generate_structured(
        self,
        *,
        task_name: str,
        system_prompt: str,
        user_prompt: str,
        response_model: type[T],
    ) -> T:
        schema = response_model.model_json_schema() if hasattr(response_model, "model_json_schema") else {}
        prompt = build_structured_output_prompt(
            system_prompt=system_prompt,
            schema_json=json.dumps(schema),
            user_prompt=user_prompt,
        )
        try:
            response = requests.post(
                f"{self.base_url}/api/generate",
                json={"model": self.model, "prompt": prompt, "stream": False, "format": "json"},
                timeout=self.timeout,
            )
            response.raise_for_status()
            raw_text = response.json().get("response", "")
            data = json.loads(raw_text)
            return validate_model(response_model, data)
        except (requests.RequestException, json.JSONDecodeError, ValidationError) as exc:
            repaired = self._repair(response_model, str(exc), locals().get("raw_text", ""))
            if repaired is not None:
                return repaired
            raise ProviderFailure(f"Ollama did not return valid structured output: {exc}", locals().get("raw_text", "")) from exc

    def _repair(self, response_model: type[T], error: str, raw_text: str) -> T | None:
        prompt = build_repair_prompt(validation_error=error, raw_text=raw_text)
        try:
            response = requests.post(
                f"{self.base_url}/api/generate",
                json={"model": self.model, "prompt": prompt, "stream": False, "format": "json"},
                timeout=self.timeout,
            )
            response.raise_for_status()
            return validate_model(response_model, json.loads(response.json().get("response", "")))
        except Exception:
            return None


def _fetch_ollama_models(base_url: str, timeout: int | float) -> tuple[list[str], str]:
    try:
        response = requests.get(f"{base_url.rstrip('/')}/api/tags", timeout=timeout)
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        return [], f"Ollama connection failed: {exc}"
    except ValueError as exc:
        return [], f"Ollama did not return a readable model list: {exc}"

    names = []
    for item in payload.get("models", []):
        name = str(item.get("name", "")).strip()
        if name:
            names.append(name)
    models = sorted(dict.fromkeys(names), key=str.lower)
    if not models:
        return [], "Connected to Ollama, but no local models were detected."
    return models, f"Detected {len(models)} local Ollama model{'s' if len(models) != 1 else ''}."


def list_ollama_models(base_url: str, timeout: int | float = OLLAMA_DISCOVERY_TIMEOUT) -> list[str]:
    models, _message = _fetch_ollama_models(base_url, timeout)
    return models


def resolve_ollama_model_name(requested_model: str, available_models: list[str]) -> str:
    requested = str(requested_model or "").strip()
    models = [str(model).strip() for model in available_models if str(model).strip()]
    if not requested or not models:
        return ""
    if requested in models:
        return requested
    base_matches = [model for model in models if model.split(":", 1)[0] == requested]
    if len(base_matches) == 1:
        return base_matches[0]
    return ""


def provider_selection_value(settings: dict, available_models: list[str]) -> str:
    if settings.get("active_provider") != "ollama":
        return "deterministic"
    model = resolve_ollama_model_name(settings.get("ollama_model", ""), available_models)
    if not model:
        return "deterministic"
    return f"{OLLAMA_PROVIDER_PREFIX}{model}"


def get_provider() -> AIProvider:
    settings = load_settings()
    if settings.get("active_provider") == "ollama":
        base_url = settings.get("ollama_base_url") or current_app.config["AX_OLLAMA_BASE_URL"]
        timeout = _coerce_timeout(settings.get("ollama_timeout") or current_app.config["AX_OLLAMA_TIMEOUT"])
        models = list_ollama_models(base_url, min(timeout, OLLAMA_DISCOVERY_TIMEOUT))
        model = resolve_ollama_model_name(settings.get("ollama_model", ""), models)
        if not model:
            return DeterministicDemoProvider()
        return OllamaProvider(
            base_url,
            model,
            timeout,
        )
    return DeterministicDemoProvider()


def test_ollama_connection(base_url: str, model: str, timeout: int) -> tuple[bool, str]:
    models, message = _fetch_ollama_models(base_url, _coerce_timeout(timeout))
    if not models:
        return False, message
    if model and not resolve_ollama_model_name(model, models):
        return False, f"Connected, but model '{model}' was not listed."
    return True, message
