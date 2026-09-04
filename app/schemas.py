from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError


def dump_model(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def validate_model(model_type: type[BaseModel], data: Any) -> BaseModel:
    if hasattr(model_type, "model_validate"):
        return model_type.model_validate(data)
    return model_type.parse_obj(data)


class ExtractedItem(BaseModel):
    category: Literal[
        "users",
        "goals",
        "tasks",
        "pain_points",
        "business_objectives",
        "requirements",
        "constraints",
        "assumptions",
        "risks",
        "open_questions",
    ]
    text: str = Field(min_length=1)
    source_reference: str = "Inference"
    is_inference: bool = False
    confidence: Literal["high", "medium", "low", "unknown"] = "medium"


class SynthesisResult(BaseModel):
    label: str = "Demo-assisted suggestions"
    items: list[ExtractedItem] = Field(default_factory=list)


class ContractSuggestion(BaseModel):
    label: str = "Demo-assisted contract suggestions"
    content_json: dict[str, Any] = Field(default_factory=dict)


class FindingSuggestion(BaseModel):
    category: str
    severity: Literal["critical", "high", "medium", "low", "observation"]
    title: str
    explanation: str
    evidence: str
    related_contract_section: str = ""
    related_workflow_node_id: str | None = None
    recommendation: str


class ReviewResult(BaseModel):
    reviewer_type: str
    summary: str
    findings: list[FindingSuggestion] = Field(default_factory=list)


class ProviderFailure(Exception):
    def __init__(self, message: str, raw: str | None = None):
        super().__init__(message)
        self.message = message
        self.raw = raw or ""


__all__ = [
    "BaseModel",
    "ContractSuggestion",
    "ExtractedItem",
    "FindingSuggestion",
    "ProviderFailure",
    "ReviewResult",
    "SynthesisResult",
    "ValidationError",
    "dump_model",
    "validate_model",
]
