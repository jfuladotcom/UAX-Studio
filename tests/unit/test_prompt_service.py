import pytest

from app.services.prompt_service import (
    PROMPT_FILES,
    build_repair_prompt,
    build_structured_output_prompt,
    get_prompt,
)


def test_prompt_registry_points_to_readable_markdown():
    for key in PROMPT_FILES:
        assert get_prompt(key)


def test_structured_output_prompt_renders_runtime_values():
    prompt = build_structured_output_prompt(
        system_prompt="Extract fields carefully.",
        schema_json='{"type": "object"}',
        user_prompt="Source material",
    )

    assert "Extract fields carefully." in prompt
    assert '{"type": "object"}' in prompt
    assert "Source material" in prompt
    assert "{{" not in prompt


def test_repair_prompt_renders_runtime_values():
    prompt = build_repair_prompt(validation_error="Bad JSON", raw_text="{broken")

    assert "Bad JSON" in prompt
    assert "{broken" in prompt
    assert "{{" not in prompt


def test_unknown_prompt_key_fails_with_available_keys():
    with pytest.raises(KeyError, match="Unknown prompt key 'missing_prompt'"):
        get_prompt("missing_prompt")
