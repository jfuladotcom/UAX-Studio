"""Translate old application-generated copy without rewriting saved projects."""


def current_ui_copy(value: str) -> str:
    return {
        "Key details generated.": "Background Information analyzed for Build Instructions.",
        "Build instruction suggestions merged from key details.": "Build Instructions generated from saved Background Information.",
        "Key details ready": "Draft ready",
        "Included synthesis informs contract suggestions.": "Saved background information informs Build Instructions.",
        "Source material creates editable synthesis.": "Saved background information guides the build draft.",
    }.get(value, value)
