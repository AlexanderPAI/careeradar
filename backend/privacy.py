import re
from typing import Any

MAX_LLM_RESUME_CHARS = 24_000

PROFILE_FIELDS_FOR_ANALYSIS = {
    "target_positions",
    "skills",
    "experience_years",
    "experience_level",
    "industries",
    "languages",
    "education",
    "summary",
}
PROFILE_FIELDS_FOR_SEARCH = PROFILE_FIELDS_FOR_ANALYSIS | {
    "salary_expectation",
    "preferred_schedule",
    "preferred_employment",
    "location",
}

_REDACTIONS = (
    (re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", re.IGNORECASE), "[EMAIL]"),
    (
        re.compile(
            r"(?<!\d)(?:\+?7|8)[\s().-]*\d{3}[\s().-]*\d{3}[\s-]*\d{2}[\s-]*\d{2}(?!\d)"
        ),
        "[PHONE]",
    ),
    (re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE), "[URL]"),
    (re.compile(r"(?<!\w)@[A-Za-z0-9_]{3,}"), "[HANDLE]"),
    (re.compile(r"(?<!\d)\d{3}-\d{3}-\d{3}\s\d{2}(?!\d)"), "[SNILS]"),
    (
        re.compile(r"(?<!\d)\d{2}\s?\d{2}\s?\d{6}(?!\d)"),
        "[PASSPORT]",
    ),
)

_SENSITIVE_LINE = re.compile(
    r"^\s*(?:фио|ф\.?\s*и\.?\s*о\.?|имя|телефон|тел\.?|e-?mail|почта|"
    r"адрес|место проживания|дата рождения|гражданство|семейное положение)"
    r"\s*[:—-].*$",
    re.IGNORECASE,
)
_POSSIBLE_NAME_LINE = re.compile(
    r"^\s*[A-ZА-ЯЁ][a-zа-яё-]+(?:\s+[A-ZА-ЯЁ][a-zа-яё-]+){1,2}\s*$"
)


def anonymize_text(value: str | None, *, limit: int = MAX_LLM_RESUME_CHARS) -> str:
    """Remove common direct identifiers and cap data sent to an external LLM."""
    lines = []
    for line_index, line in enumerate((value or "").splitlines()):
        if _SENSITIVE_LINE.match(line):
            continue
        if line_index < 8 and _POSSIBLE_NAME_LINE.match(line):
            continue
        for pattern, replacement in _REDACTIONS:
            line = pattern.sub(replacement, line)
        lines.append(line)
    return "\n".join(lines)[:limit]


def minimal_profile(
    profile: dict[str, Any], *, purpose: str = "analysis"
) -> dict[str, Any]:
    """Return only fields required for career analysis, without identity fields."""
    fields = (
        PROFILE_FIELDS_FOR_SEARCH
        if purpose == "search"
        else PROFILE_FIELDS_FOR_ANALYSIS
    )
    result: dict[str, Any] = {}
    for key in fields:
        value = profile.get(key)
        if value in (None, "", []):
            continue
        if isinstance(value, str):
            value = anonymize_text(value, limit=4_000)
            if key == "location":
                value = value.split(",", maxsplit=1)[0].strip()[:100]
        elif isinstance(value, list):
            value = [
                anonymize_text(str(item), limit=500)
                for item in value[:50]
                if str(item).strip()
            ]
        result[key] = value
    return result


def require_llm_consent(consent: bool) -> None:
    if not consent:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=403,
            detail="Для внешней LLM-обработки требуется явное согласие пользователя",
        )
