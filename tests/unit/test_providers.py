from app.schemas import ContractSuggestion, ReviewResult, SynthesisResult
from app.services.providers import (
    DeterministicDemoProvider,
    OllamaProvider,
    get_provider,
    provider_selection_value,
)
from app.services.settings import save_settings


def test_deterministic_provider_returns_valid_structures():
    provider = DeterministicDemoProvider()
    synthesis = provider.generate_structured(
        task_name="intake_synthesis",
        system_prompt="",
        user_prompt="artist artwork submission review",
        response_model=SynthesisResult,
    )
    assert synthesis.items
    assert synthesis.items[0].source_reference

    contract = provider.generate_structured(
        task_name="contract_suggestions",
        system_prompt="",
        user_prompt="support ticket triage review checkpoints",
        response_model=ContractSuggestion,
    )
    assert "autonomy_controls" in contract.content_json
    problem = contract.content_json["product_intent"]["fields"]["problem_statement"]["value"]
    assert "artist" not in problem.lower()

    review = provider.generate_structured(
        task_name="review_trust_safety_critic",
        system_prompt="",
        user_prompt="review",
        response_model=ReviewResult,
    )
    assert review.findings[0].severity in {"critical", "high", "medium", "low", "observation"}


def test_get_provider_defaults_to_deterministic_when_ollama_model_is_missing(app, monkeypatch):
    with app.app_context():
        save_settings(
            {
                "active_provider": "ollama",
                "ollama_base_url": "http://127.0.0.1:11434",
                "ollama_model": "llama3",
                "ollama_timeout": 20,
            }
        )
        monkeypatch.setattr("app.services.providers.list_ollama_models", lambda *_args: [])

        provider = get_provider()

    assert isinstance(provider, DeterministicDemoProvider)


def test_get_provider_uses_detected_ollama_model(app, monkeypatch):
    with app.app_context():
        save_settings(
            {
                "active_provider": "ollama",
                "ollama_base_url": "http://127.0.0.1:11434",
                "ollama_model": "llama3",
                "ollama_timeout": 20,
            }
        )
        monkeypatch.setattr("app.services.providers.list_ollama_models", lambda *_args: ["llama3:latest"])

        provider = get_provider()

    assert isinstance(provider, OllamaProvider)
    assert provider.model == "llama3:latest"


def test_provider_selection_value_defaults_when_saved_model_is_not_detected():
    selected = provider_selection_value({"active_provider": "ollama", "ollama_model": "llama3"}, [])

    assert selected == "deterministic"


def test_provider_selection_value_targets_detected_model():
    selected = provider_selection_value(
        {"active_provider": "ollama", "ollama_model": "llama3"},
        ["llama3:latest"],
    )

    assert selected == "ollama::llama3:latest"
