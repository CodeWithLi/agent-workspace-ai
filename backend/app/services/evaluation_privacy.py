import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RedactedEvaluationText:
    text: str
    count: int
    categories: tuple[str, ...]


_REDACTION_RULES = (
    (
        "credential",
        re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/=-]{8,}"),
        "Bearer [CREDENTIAL_REDACTED]",
    ),
    (
        "credential",
        re.compile(
            r"(?i)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|token|secret|password|passwd)"
            r"(\s*[:=]\s*)[^\s,;，；]{4,}"
        ),
        lambda match: f"{match.group(1)}{match.group(2)}[CREDENTIAL_REDACTED]",
    ),
    (
        "credential",
        re.compile(r"(?i)(?<![a-z0-9])(?:sk|rk|pk)-[a-z0-9_-]{12,}"),
        "[CREDENTIAL_REDACTED]",
    ),
    (
        "email",
        re.compile(r"(?i)(?<![\w.+-])[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9-]+(?:\.[a-z0-9-]+)+"),
        "[EMAIL_REDACTED]",
    ),
    (
        "id_number",
        re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)"),
        "[ID_REDACTED]",
    ),
    (
        "phone",
        re.compile(r"(?<!\d)(?:\+?86[-\s]?)?1[3-9]\d{9}(?!\d)"),
        "[PHONE_REDACTED]",
    ),
    (
        "bank_card",
        re.compile(r"(?<!\d)(?:\d[ -]?){15,18}\d(?!\d)"),
        "[BANK_CARD_REDACTED]",
    ),
    (
        "ip_address",
        re.compile(r"(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)"),
        "[IP_REDACTED]",
    ),
)


def redact_evaluation_text(
    value: str | None,
    *,
    personal_names: Iterable[str] = (),
) -> RedactedEvaluationText:
    text = str(value or "")
    count = 0
    categories: list[str] = []
    for category, pattern, replacement in _REDACTION_RULES:
        text, matches = pattern.subn(replacement, text)
        if matches:
            count += matches
            if category not in categories:
                categories.append(category)
    normalized_names = set()
    for name in personal_names:
        if not isinstance(name, str):
            continue
        normalized = name.strip()
        minimum_length = 2 if any("\u4e00" <= char <= "\u9fff" for char in normalized) else 3
        if len(normalized) >= minimum_length:
            normalized_names.add(normalized)
    for name in sorted(normalized_names, key=lambda item: (-len(item), item.casefold())):
        text, matches = re.subn(re.escape(name), "[NAME_REDACTED]", text, flags=re.IGNORECASE)
        if matches:
            count += matches
            if "name" not in categories:
                categories.append("name")
    return RedactedEvaluationText(text=text, count=count, categories=tuple(categories))


def redact_evaluation_case_values(
    values: Mapping[str, Any],
    *,
    personal_names: Iterable[str] = (),
) -> dict[str, Any]:
    output = dict(values)
    for field in ("name", "input_text", "rubric"):
        if field in output:
            output[field] = redact_evaluation_text(
                str(output[field] or ""),
                personal_names=personal_names,
            ).text
    for field in ("expected_keywords", "forbidden_keywords"):
        if field in output:
            output[field] = [
                redact_evaluation_text(str(value), personal_names=personal_names).text
                for value in output[field]
            ]
    return output
