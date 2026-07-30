import re
from dataclasses import dataclass
from urllib.parse import urlsplit


@dataclass(frozen=True)
class VacancyUrl:
    url: str
    source: str


_ALLOWED_URLS = (
    (
        "hh",
        re.compile(r"(?:[a-z0-9-]+\.)*hh\.ru", re.IGNORECASE),
        re.compile(r"/vacancy/([0-9]+)"),
        "hh.ru",
        "vacancy",
    ),
    (
        "habr",
        re.compile(r"career\.habr\.com", re.IGNORECASE),
        re.compile(r"/vacancies/([0-9]+)"),
        "career.habr.com",
        "vacancies",
    ),
)


def validate_vacancy_url(value: object) -> VacancyUrl:
    """Validate and return a canonical URL for a supported vacancy."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Vacancy URL is empty")

    try:
        parsed = urlsplit(value.strip())
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Vacancy URL is malformed") from exc

    hostname = (parsed.hostname or "").lower()
    if (
        parsed.scheme.lower() != "https"
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
    ):
        raise ValueError("Vacancy URL must use HTTPS without credentials")

    path = parsed.path.rstrip("/")
    for (
        source,
        host_pattern,
        path_pattern,
        canonical_host,
        canonical_segment,
    ) in _ALLOWED_URLS:
        if host_pattern.fullmatch(hostname):
            match = path_pattern.fullmatch(path)
            if match is None:
                raise ValueError("Vacancy URL path is not allowed")
            vacancy_id = match.group(1)
            return VacancyUrl(
                url=f"https://{canonical_host}/{canonical_segment}/{vacancy_id}",
                source=source,
            )

    raise ValueError("Vacancy URL hostname is not allowed")


def safe_vacancy_url(value: object) -> str | None:
    """Return a display-safe canonical URL, or None for untrusted values."""
    try:
        return validate_vacancy_url(value).url
    except ValueError:
        return None
