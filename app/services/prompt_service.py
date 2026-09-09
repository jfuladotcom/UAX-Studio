from __future__ import annotations

from pathlib import Path

PROMPT_DIR = Path(__file__).resolve().parents[1] / "prompts"

# Add new prompt keys here, then create the matching Markdown file in app/prompts.
PROMPT_FILES = {
    "intake_synthesis": "intake_synthesis.md",
    "contract_suggestions": "contract_suggestions.md",
    "review_quality": "review_quality.md",
    "demo_seed_synthesis": "demo_seed_synthesis.md",
    "demo_seed_contract": "demo_seed_contract.md",
    "fallback_review": "fallback_review.md",
    "structured_output": "structured_output.md",
    "repair_json": "repair_json.md",
}


def list_prompt_keys() -> list[str]:
    return sorted(PROMPT_FILES)


def get_prompt(key: str) -> str:
    try:
        filename = PROMPT_FILES[key]
    except KeyError:
        available = ", ".join(list_prompt_keys())
        raise KeyError(f"Unknown prompt key '{key}'. Available prompts: {available}") from None

    path = _safe_prompt_path(filename)
    try:
        return path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        raise FileNotFoundError(f"Prompt file for '{key}' was not found: {path}") from None


def render_prompt(key: str, **values: object) -> str:
    prompt = get_prompt(key)
    for name, value in values.items():
        text = str(value)
        prompt = prompt.replace(f"{{{{ {name} }}}}", text)
        prompt = prompt.replace(f"{{{{{name}}}}}", text)
    return prompt.strip()


def build_structured_output_prompt(*, system_prompt: str, schema_json: str, user_prompt: str) -> str:
    return render_prompt(
        "structured_output",
        system_prompt=system_prompt,
        response_schema=schema_json,
        user_prompt=user_prompt,
    )


def build_repair_prompt(*, validation_error: str, raw_text: str) -> str:
    return render_prompt("repair_json", validation_error=validation_error, raw_text=raw_text)


def _safe_prompt_path(filename: str) -> Path:
    root = PROMPT_DIR.resolve()
    path = (root / filename).resolve()
    if path != root and root not in path.parents:
        raise ValueError(f"Prompt path escapes prompt directory: {filename}")
    return path
