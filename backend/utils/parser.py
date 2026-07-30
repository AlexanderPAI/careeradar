import asyncio
import csv
import html as html_lib
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlencode, urlparse

import aiohttp
from playwright.async_api import async_playwright

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("PARSER")

# DEFAULT
AREA = 1  # 1 = Москва; 0 = вся Россия
MAX_PAGES = 3  # страниц на каждый запрос (50 вакансий / страница)
RESULTS_JSON = "hh_vacancies.json"
RESULTS_CSV = "hh_vacancies.csv"

# Справочники значений hh.ru
SCHEDULE_LABELS = {
    "remote": "Удалённая",
    "fullDay": "Полный день",
    "flexible": "Гибкий",
    "shift": "Сменный",
    "flyInFlyOut": "Вахта",
}

EXPERIENCE_LABELS = {
    "noExperience": "Без опыта",
    "between1And3": "1–3 года",
    "between3And6": "3–6 лет",
    "moreThan6": "Более 6 лет",
}

EMPLOYMENT_LABELS = {
    "full": "Полная",
    "part": "Частичная",
    "project": "Проектная",
    "volunteer": "Волонтёрство",
    "probation": "Стажировка",
}

ORDER_LABELS = {
    "relevance": "По соответствию",
    "salary_desc": "По убыванию ЗП",
    "salary_asc": "По возрастанию ЗП",
    "name": "По названию",
    "publication_time": "По дате публикации",
}


# Фильтры
@dataclass
class SearchFilters:
    """
    Параметры фильтрации поиска вакансий на hh.ru.

    URL-фильтры  (передаются напрямую в запрос к hh.ru)
    ────────────────────────────────────────────────────
    salary_from      : int | None
        Минимальная ЗП в ₽. hh.ru вернёт вакансии, где указанная ЗП ≥ этого значения.
        Пример: 150_000

    only_with_salary : bool
        Показывать только вакансии с указанной зарплатой.

    schedule         : list[str]
        Формат/график работы (несколько значений — ИЛИ).
        Допустимые значения:
            'remote'      — удалённая работа
            'fullDay'     — полный день (офис)
            'flexible'    — гибкий график
            'shift'       — сменный график
            'flyInFlyOut' — вахта

    experience       : list[str]
        Требуемый опыт (несколько значений — ИЛИ).
        Допустимые значения:
            'noExperience' — без опыта
            'between1And3' — 1–3 года
            'between3And6' — 3–6 лет
            'moreThan6'    — более 6 лет

    employment       : list[str]
        Тип занятости (несколько значений — ИЛИ).
        Допустимые значения:
            'full'      — полная
            'part'      — частичная
            'project'   — проектная
            'volunteer' — волонтёрство
            'probation' — стажировка

    order_by         : str
        Сортировка результатов.
        Допустимые значения:
            'relevance'        — по соответствию (по умолчанию)
            'salary_desc'      — по убыванию зарплаты
            'salary_asc'       — по возрастанию зарплаты
            'name'             — по названию
            'publication_time' — по дате публикации

    search_field     : str
        Область поиска текста запроса.
        ''     — везде (название + описание, по умолчанию)
        'name' — только в названии вакансии

    Пост-фильтры  (применяются к уже собранным результатам)
    ─────────────────────────────────────────────────────────
    salary_to         : int | None
        Верхняя граница ЗП в ₽. Если минимальная ЗП в вакансии явно превышает
        это значение — вакансия отсеивается. Вакансии без ЗП сохраняются.
        Пример: 300_000

    exclude_companies : list[str]
        Исключить вакансии компаний, чьё название содержит любую из подстрок
        (без учёта регистра).
        Пример: ["HeadHunter", "Яндекс"]

    require_keywords  : list[str]
        Оставить только вакансии, в названии которых присутствуют ВСЕ слова из списка
        (без учёта регистра).
        Пример: ["AI", "backend"]

    exclude_keywords  : list[str]
        Исключить вакансии, в названии которых есть ХОТЯ БЫ ОДНО слово из списка
        (без учёта регистра).
        Пример: ["стажёр", "junior", "intern"]
    """

    # URL-фильтры
    salary_from: int | None = None
    only_with_salary: bool = False
    schedule: list[str] = field(default_factory=list)
    experience: list[str] = field(default_factory=list)
    employment: list[str] = field(default_factory=list)
    order_by: str = "relevance"
    search_field: str = ""

    # Пост-фильтры
    salary_to: int | None = None
    exclude_companies: list[str] = field(default_factory=list)
    require_keywords: list[str] = field(default_factory=list)
    exclude_keywords: list[str] = field(default_factory=list)


class HHParser:

    REQUEST_TIMEOUT_SECONDS = 60
    REQUEST_HEADERS = {
        "Accept": "application/json,text/html,application/xhtml+xml",
        "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
        "User-Agent": "Careeradar/0.4 (single vacancy parser)",
    }

    def __init__(
        self,
        search_queries: list[str],
        area: int,
        max_pages: int,
        filters: SearchFilters | None = None,
        save_to_json: bool = False,
        save_to_csv: bool = False,
        results_json_path: Optional[str] = RESULTS_JSON,
        results_csv_path: Optional[str] = RESULTS_CSV,
        csv_override: bool = False,
    ) -> None:
        self.search_queries = search_queries
        self.area = area
        self.max_pages = max_pages
        self.filters = filters or SearchFilters()
        self.results_json_path = results_json_path
        self.results_csv_path = results_csv_path
        self.save_to_json = save_to_json
        self.save_to_csv = save_to_csv
        self.csv_override = csv_override
        self.results = []

    def _build_url(self, query: str, page_num: int) -> str:
        """Строит URL запроса с учётом всех URL-фильтров.

        Списковые параметры (schedule, experience, employment) urlencode разворачивает
        в повторяющиеся ключи: schedule=remote&schedule=flexible и т.д.
        None-значения отсеиваются до передачи в urlencode — незаданные фильтры
        просто не попадают в URL.
        """
        filters = self.filters

        param_map = {
            "text": query,
            "area": self.area,
            "page": page_num,
            "per_page": 20,
            "salary": filters.salary_from,
            "only_with_salary": "true" if filters.only_with_salary else None,
            "schedule": filters.schedule or None,
            "experience": filters.experience or None,
            "employment": filters.employment or None,
            "order_by": filters.order_by if filters.order_by != "relevance" else None,
            "search_field": filters.search_field or None,
        }

        active_params = {
            key: value for key, value in param_map.items() if value is not None
        }
        return "https://hh.ru/search/vacancy?" + urlencode(active_params, doseq=True)

    @staticmethod
    def _clean(text: str) -> str:
        return re.sub(r"\s+", " ", text or "").strip()

    @staticmethod
    def _clean_html(value: object) -> str:
        if value is None:
            return ""
        text = html_lib.unescape(str(value))
        text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"<li[^>]*>", "\n• ", text, flags=re.IGNORECASE)
        text = re.sub(r"</li>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"</(?:p|div|h[1-6])>", "\n\n", text, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", "", text)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n\s*\n+", "\n\n", text)
        return text.strip()

    @staticmethod
    def _normalize_search_result_url(href: str | None) -> str:
        """Turn HH's relative card href into an absolute URL for final validation."""
        if not href:
            return "—"
        href_without_query = href.split("?", 1)[0].strip()
        if href_without_query.startswith("/vacancy/"):
            return f"https://hh.ru{href_without_query}"
        return href_without_query

    @staticmethod
    def _vacancy_id_from_url(
        url: str,
        *,
        allowed_hosts: set[str],
        path_pattern: str,
        allow_subdomains: bool = False,
    ) -> str:
        parsed = urlparse(url.strip())
        host = (parsed.hostname or "").lower()
        host_allowed = host in allowed_hosts or (
            allow_subdomains
            and any(host.endswith(f".{allowed}") for allowed in allowed_hosts)
        )
        if parsed.scheme != "https" or not host_allowed:
            expected_host = sorted(allowed_hosts)[0]
            raise ValueError(f"Ожидается ссылка на вакансию с домена {expected_host}")

        match = re.fullmatch(path_pattern, parsed.path.rstrip("/"))
        if match is None:
            raise ValueError("Не удалось определить идентификатор вакансии")
        return match.group(1)

    @staticmethod
    def _format_detail_salary(salary: dict | None) -> str:
        if not salary:
            return "не указана"

        salary_from = salary.get("from")
        salary_to = salary.get("to")
        currency = salary.get("currency") or ""
        if salary_from is not None and salary_to is not None:
            amount = f"{salary_from:,}–{salary_to:,}"
        elif salary_from is not None:
            amount = f"от {salary_from:,}"
        elif salary_to is not None:
            amount = f"до {salary_to:,}"
        else:
            return "не указана"

        tax = "до вычета налогов" if salary.get("gross") else "на руки"
        return f"{amount.replace(',', ' ')} {currency} ({tax})".strip()

    async def parse_vacancy(self, url: str) -> dict:
        """Парсит одну вакансию hh.ru через браузер Playwright."""
        vacancy_id = self._vacancy_id_from_url(
            url,
            allowed_hosts={"hh.ru"},
            path_pattern=r"/vacancy/(\d+)",
            allow_subdomains=True,
        )
        canonical_url = f"https://hh.ru/vacancy/{vacancy_id}"

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            context = await browser.new_context(
                locale="ru-RU",
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/125.0.0.0 Safari/537.36"
                ),
            )
            page = await context.new_page()
            try:
                await self._goto_with_retry(page, canonical_url)
                await page.wait_for_selector(
                    '[data-qa="vacancy-description"]',
                    timeout=self.GOTO_TIMEOUT_MS,
                )
                return await self._parse_vacancy_page(
                    page,
                    canonical_url,
                    vacancy_id,
                )
            finally:
                await context.close()
                await browser.close()

    async def _parse_vacancy_page(
        self,
        page,
        canonical_url: str,
        vacancy_id: str,
    ) -> dict:
        async def first_text(*selectors: str, default: str = "—") -> str:
            for selector in selectors:
                locator = page.locator(selector)
                if await locator.count():
                    value = self._clean(await locator.first.inner_text())
                    if value:
                        return value
            return default

        title = await first_text('[data-qa="vacancy-title"]')
        if title == "—":
            raise ValueError("На странице HH не найдено название вакансии")

        skill_locator = page.locator('[data-qa="skills-element"]')
        skills = [
            self._clean(value)
            for value in await skill_locator.all_inner_texts()
            if self._clean(value)
        ]
        description_locator = page.locator('[data-qa="vacancy-description"]')
        description = (
            self._clean_html(await description_locator.first.inner_html())
            if await description_locator.count()
            else ""
        )
        published_locator = page.locator('[data-qa="vacancy-creation-time"] time, time')
        published_at = (
            await published_locator.first.get_attribute("datetime")
            if await published_locator.count()
            else None
        )

        return {
            "source": "hh",
            "external_id": vacancy_id,
            "title": title,
            "company": await first_text(
                '[data-qa="vacancy-company-name"]',
                '[data-qa="vacancy-company-name"] a',
            ),
            "salary": await first_text(
                '[data-qa="vacancy-salary"]',
                '[data-qa="vacancy-compensation"]',
                default="не указана",
            ),
            "city": await first_text(
                '[data-qa="vacancy-view-raw-address"]',
                '[data-qa="vacancy-view-location"]',
            ),
            "schedule": await first_text(
                '[data-qa="work-schedule-by-days-text"]',
                '[data-qa="vacancy-view-employment-mode"]',
            ),
            "employment": await first_text('[data-qa="vacancy-view-employment-mode"]'),
            "experience": await first_text('[data-qa="vacancy-experience"]'),
            "skills": skills,
            "description": description,
            "published_at": published_at,
            "link": canonical_url,
        }

    @staticmethod
    def _salary_from_card(card) -> str:
        """
        Ищет зарплату в карточке: сначала через data-qa-compensation,
        потом через любой элемент с «₽» в тексте.
        """
        return None

    # Field parsers

    async def _get_salary(self, card) -> str:
        """Async-вариант: проходит по всем span/div карточки в поисках ₽."""
        salary_els = await card.query_selector_all(
            '[data-qa*="vacancy-serp__vacancy-compensation"]'
        )
        for salary_el in salary_els:
            salary_text = self._clean(await salary_el.inner_text())
            if salary_text and "₽" in salary_text:
                return salary_text

        all_els = await card.query_selector_all("span, div")
        for element in all_els:
            element_text = self._clean(await element.inner_text())
            if "₽" in element_text and len(element_text) < 80:
                cleaned_amount = re.sub(
                    r"(Выплаты.*|Опыт.*|на руки|на счёт)", "", element_text, flags=re.I
                )
                cleaned_amount = self._clean(cleaned_amount)
                if cleaned_amount:
                    return cleaned_amount
        return "не указана"

    async def _get_schedule(self, card) -> str:
        """Формат: удалёнка / гибрид / офис."""
        remote_el = await card.query_selector(
            '[data-qa="vacancy-label-work-schedule-remote"]'
        )
        if remote_el:
            return self._clean(await remote_el.inner_text())
        return "—"

    async def _get_experience(self, card) -> str:
        """Требуемый опыт."""
        experience_el = await card.query_selector(
            '[data-qa*="vacancy-serp__vacancy-work-experience"]'
        )
        if experience_el:
            return self._clean(await experience_el.inner_text())
        return "—"

    # Page parser

    async def parse_page(self, page) -> list[dict]:
        """Парсит все карточки с текущей страницы выдачи."""
        await page.wait_for_selector(
            '[data-qa="vacancy-serp__vacancy"]', timeout=15_000
        )
        cards = await page.query_selector_all('[data-qa="vacancy-serp__vacancy"]')
        page_results = []

        for card in cards:
            try:
                title_el = await card.query_selector('[data-qa="serp-item__title"]')
                title = self._clean(await title_el.inner_text()) if title_el else "—"
                href = await title_el.get_attribute("href") if title_el else None
                link = self._normalize_search_result_url(href)

                company_el = await card.query_selector(
                    '[data-qa="vacancy-serp__vacancy-employer"]'
                )
                company = (
                    self._clean(await company_el.inner_text()) if company_el else "—"
                )

                salary = await self._get_salary(card)

                city_el = await card.query_selector(
                    '[data-qa="vacancy-serp__vacancy-address"]'
                )
                city = self._clean(await city_el.inner_text()) if city_el else "—"

                schedule = await self._get_schedule(card)
                experience = await self._get_experience(card)

                page_results.append(
                    {
                        "source": "hh",
                        "title": title,
                        "company": company,
                        "salary": salary,
                        "city": city,
                        "schedule": schedule,
                        "experience": experience,
                        "link": link,
                    }
                )
            except Exception:
                logger.error("    [!] Ошибка при разборе карточки")

        return page_results

    # Настройки retry для обхода throttling hh.ru
    GOTO_TIMEOUT_MS = 60_000  # таймаут одного перехода
    GOTO_RETRY_COUNT = 3  # попыток на каждую страницу
    GOTO_RETRY_BASE_DELAY = 5.0  # базовая задержка retry (умножается на номер попытки)
    PAGE_DELAY_MS = 1_500  # пауза после загрузки страницы
    BETWEEN_PAGES_DELAY = 2.0  # пауза между страницами одного запроса

    async def _goto_with_retry(self, page, url: str) -> None:
        """Переходит по URL с повторными попытками при таймауте."""
        for attempt in range(self.GOTO_RETRY_COUNT):
            try:
                await page.goto(
                    url, wait_until="domcontentloaded", timeout=self.GOTO_TIMEOUT_MS
                )
                return
            except Exception:
                if attempt == self.GOTO_RETRY_COUNT - 1:
                    raise
                delay = self.GOTO_RETRY_BASE_DELAY * (attempt + 1)
                logger.warning(
                    "    [!] Таймаут (попытка %d), повтор через %.0fс",
                    attempt + 1,
                    delay,
                )
                await asyncio.sleep(delay)

    async def search(self, browser, query: str) -> list[dict]:
        """Ищет вакансии по одному запросу, обходит max_pages страниц."""
        ctx = await browser.new_context(
            locale="ru-RU",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
        )
        page = await ctx.new_page()
        all_results: list[dict] = []

        try:
            for page_num in range(self.max_pages):
                url = self._build_url(query, page_num)
                logger.info("  ↳ страница %d", page_num + 1)

                if page_num > 0:
                    await asyncio.sleep(self.BETWEEN_PAGES_DELAY)

                await self._goto_with_retry(page, url)
                await page.wait_for_timeout(self.PAGE_DELAY_MS)

                content = await page.content()
                if "Ничего не найдено" in content:
                    logger.info("    [!] Нет результатов — стоп")
                    break

                try:
                    await page.wait_for_selector(
                        '[data-qa="vacancy-serp__vacancy"]', timeout=8_000
                    )
                except Exception:
                    logger.info("    [!] Карточки не появились — стоп")
                    break

                page_vacancies = await self.parse_page(page)
                if not page_vacancies:
                    break

                for vacancy in page_vacancies:
                    vacancy["query"] = query
                all_results.extend(page_vacancies)
                logger.info(f"    ✓ найдено: {len(page_vacancies)}")

                next_btn = await page.query_selector('[data-qa="pager-next"]')
                if not next_btn:
                    break

        finally:
            await ctx.close()

        return all_results

    # Post-filters

    def _apply_filters(self, data: list[dict]) -> list[dict]:
        """Применяет пост-фильтры к собранным вакансиям."""
        filters = self.filters
        result = data

        # Исключить компании по подстроке
        if filters.exclude_companies:
            excluded_names = [company.lower() for company in filters.exclude_companies]
            before = len(result)
            result = [
                vacancy
                for vacancy in result
                if not any(
                    excluded in vacancy["company"].lower()
                    for excluded in excluded_names
                )
            ]
            logger.info(f"  exclude_companies: {before} → {len(result)}")

        # Обязательные слова в названии (все сразу)
        if filters.require_keywords:
            required_words = [keyword.lower() for keyword in filters.require_keywords]
            before = len(result)
            result = [
                vacancy
                for vacancy in result
                if all(word in vacancy["title"].lower() for word in required_words)
            ]
            logger.info(f"  require_keywords:  {before} → {len(result)}")

        # Запрещённые слова в названии (хотя бы одно — убираем)
        if filters.exclude_keywords:
            excluded_words = [keyword.lower() for keyword in filters.exclude_keywords]
            before = len(result)
            result = [
                vacancy
                for vacancy in result
                if not any(word in vacancy["title"].lower() for word in excluded_words)
            ]
            logger.info(f"  exclude_keywords:  {before} → {len(result)}")

        # Верхняя граница ЗП (пост-фильтр, т.к. hh.ru поддерживает только salary_from)
        if filters.salary_to:
            before = len(result)
            filtered_by_salary = []
            for vacancy in result:
                salary_str = vacancy["salary"]
                if salary_str == "не указана":
                    filtered_by_salary.append(vacancy)
                    continue
                # Извлекаем все числа из строки вида "100 000 – 200 000 ₽"
                salary_numbers = [
                    int(re.sub(r"\s|\u202f", "", num_str))
                    for num_str in re.findall(
                        r"[\d][\d\s\u202f]*[\d]|[\d]+", salary_str
                    )
                    if re.sub(r"\s|\u202f", "", num_str).isdigit()
                ]
                # Если минимум диапазона явно выше лимита — пропускаем
                if salary_numbers and min(salary_numbers) > filters.salary_to:
                    continue
                filtered_by_salary.append(vacancy)
            result = filtered_by_salary
            logger.info(f"  salary_to:         {before} → {len(result)}")

        return result

    # Saving

    def save_json(self, data: list[dict]) -> None:
        with open(self.results_json_path, "w", encoding="utf-8") as output_file:
            json.dump(data, output_file, ensure_ascii=False, indent=2)
        logger.info(f"  ✓ {self.results_json_path}  ({len(data)} записей)")

    def save_csv(self, data: list[dict]) -> None:
        if not data:
            return
        fields = [
            "title",
            "company",
            "salary",
            "city",
            "schedule",
            "experience",
            "link",
            "query",
        ]
        with open(
            self.results_csv_path, "w", newline="", encoding="utf-8-sig"
        ) as output_file:
            writer = csv.DictWriter(output_file, fieldnames=fields)
            writer.writeheader()
            writer.writerows(data)
        logger.info(f"  ✓ {self.results_csv_path}")

    def deduplicate(self, data: list[dict]) -> list[dict]:
        seen_links, unique_vacancies = set(), []
        for vacancy in data:
            if vacancy["link"] not in seen_links:
                seen_links.add(vacancy["link"])
                unique_vacancies.append(vacancy)
        return unique_vacancies

    def _log_filters(self) -> None:
        """Логирует все активные фильтры."""
        # todo плохой вонючий код - подумать как переделать
        filters = self.filters
        search_field_label = (
            "названию" if filters.search_field == "name" else filters.search_field
        )

        descriptions = {
            "ЗП от": f"{filters.salary_from:,} ₽" if filters.salary_from else None,
            "ЗП до": f"{filters.salary_to:,} ₽" if filters.salary_to else None,
            "только с ЗП": "да" if filters.only_with_salary else None,
            "график": ", ".join(
                SCHEDULE_LABELS.get(val, val) for val in filters.schedule
            )
            or None,
            "опыт": ", ".join(
                EXPERIENCE_LABELS.get(val, val) for val in filters.experience
            )
            or None,
            "занятость": ", ".join(
                EMPLOYMENT_LABELS.get(val, val) for val in filters.employment
            )
            or None,
            "сортировка": (
                ORDER_LABELS.get(filters.order_by, filters.order_by)
                if filters.order_by != "relevance"
                else None
            ),
            "поиск по": search_field_label if filters.search_field else None,
            "исключить компании": (
                ", ".join(filters.exclude_companies)
                if filters.exclude_companies
                else None
            ),
            "обязательные слова": (
                ", ".join(filters.require_keywords)
                if filters.require_keywords
                else None
            ),
            "исключить слова": (
                ", ".join(filters.exclude_keywords)
                if filters.exclude_keywords
                else None
            ),
        }

        active_filters = {
            label: value for label, value in descriptions.items() if value
        }

        logger.info("  Активных фильтров: %d", len(active_filters))

    async def run_parser(self) -> list[dict]:
        logger.info("=" * 60)
        logger.info("  hh.ru Parser")
        logger.info("  Количество запросов: %d", len(self.search_queries))
        logger.info("  Страниц на запрос: %d", self.max_pages)
        self._log_filters()
        logger.info("=" * 60)

        all_vacancies: list[dict] = []

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)

            for query_index, query in enumerate(self.search_queries, start=1):
                logger.info("[→] Запрос %d/%d", query_index, len(self.search_queries))
                results = await self.search(browser, query)
                all_vacancies.extend(results)
                logger.info(f"    Итого: {len(results)}")
                await asyncio.sleep(3.0)

            await browser.close()

        unique_vacancies = self.deduplicate(all_vacancies)
        logger.info(f"\n{'─' * 60}")
        logger.info(f"Уникальных вакансий (до пост-фильтров): {len(unique_vacancies)}")

        filtered_vacancies = self._apply_filters(unique_vacancies)
        logger.info(
            f"Уникальных вакансий (после пост-фильтров): {len(filtered_vacancies)}"
        )
        logger.info(f"{'─' * 60}")

        if self.save_to_json:
            self.save_json(filtered_vacancies)
        if self.save_to_csv:
            self.save_csv(filtered_vacancies)

        logger.info(f"\n{'─' * 60}")
        logger.info("Результатов для выдачи: %d", len(filtered_vacancies))
        logger.info(f"{'─' * 60}")

        return filtered_vacancies


class CareerHabrParser(HHParser):
    """Парсер вакансий career.habr.com с тем же CSV-контрактом, что и HHParser."""

    BETWEEN_PAGES_DELAY = 1.0

    def _build_url(self, query: str, page_num: int) -> str:
        """Строит URL поиска Career Habr.

        У Habr Career другая модель фильтров, поэтому через URL отправляем только
        устойчивые параметры поиска. Остальные ограничения применяются пост-фильтрами.
        """
        params: dict[str, object] = {
            "type": "all",
            "q": query,
            "page": page_num + 1,
        }
        if self.area == 1:
            params["city_id"] = 678  # Москва

        return "https://career.habr.com/vacancies?" + urlencode(params, doseq=True)

    @staticmethod
    def _extract_ssr_state(page_html: str) -> dict:
        match = re.search(
            r'<script[^>]+data-ssr-state=["\']true["\'][^>]*>(.*?)</script>',
            page_html,
            re.DOTALL,
        )
        if not match:
            return {}

        raw_json = html_lib.unescape(match.group(1))
        try:
            return json.loads(raw_json)
        except json.JSONDecodeError:
            logger.error("    [!] Не удалось разобрать SSR JSON Habr")
            return {}

    @staticmethod
    def _format_habr_salary(vacancy: dict) -> str:
        salary = vacancy.get("salary") or {}
        formatted_salary = salary.get("formatted")
        return formatted_salary or "не указана"

    @staticmethod
    def _format_habr_city(vacancy: dict) -> str:
        locations = vacancy.get("locations") or []
        location_titles = [
            location.get("title")
            for location in locations
            if isinstance(location, dict) and location.get("title")
        ]
        if location_titles:
            return ", ".join(location_titles)
        if vacancy.get("remoteWork"):
            return "Удалённо"
        return "—"

    @staticmethod
    def _format_habr_schedule(vacancy: dict) -> str:
        if vacancy.get("remoteWork"):
            return "Удалённо"

        employment_labels = {
            "full_time": "Полная занятость",
            "part_time": "Частичная занятость",
            "project": "Проектная работа",
            "internship": "Стажировка",
        }
        employment = vacancy.get("employment")
        return employment_labels.get(employment, "—")

    @staticmethod
    def _format_habr_experience(vacancy: dict) -> str:
        qualification = vacancy.get("qualification")
        if qualification:
            return qualification

        salary_qualification = vacancy.get("salaryQualification") or {}
        return salary_qualification.get("title") or "—"

    def _vacancy_from_habr_json(self, vacancy: dict) -> dict:
        company = vacancy.get("company") or {}
        href = vacancy.get("href") or ""
        link = f"https://career.habr.com{href}" if href.startswith("/") else href

        return {
            "source": "habr",
            "title": vacancy.get("title") or "—",
            "company": company.get("title") or "—",
            "salary": self._format_habr_salary(vacancy),
            "city": self._format_habr_city(vacancy),
            "schedule": self._format_habr_schedule(vacancy),
            "experience": self._format_habr_experience(vacancy),
            "link": link or "—",
        }

    @staticmethod
    def _extract_json_ld(page_html: str) -> list[dict]:
        blocks: list[dict] = []
        pattern = re.compile(
            r"<script[^>]*type=[\"']application/ld\+json[\"'][^>]*>" r"(.*?)</script>",
            re.IGNORECASE | re.DOTALL,
        )
        for raw_block in pattern.findall(page_html):
            try:
                parsed = json.loads(raw_block)
            except json.JSONDecodeError:
                try:
                    parsed = json.loads(html_lib.unescape(raw_block))
                except json.JSONDecodeError:
                    continue
            candidates = parsed if isinstance(parsed, list) else [parsed]
            blocks.extend(item for item in candidates if isinstance(item, dict))
        return blocks

    @classmethod
    def _extract_job_posting(cls, page_html: str) -> dict:
        for block in cls._extract_json_ld(page_html):
            graph = block.get("@graph")
            candidates = graph if isinstance(graph, list) else [block]
            for candidate in candidates:
                if not isinstance(candidate, dict):
                    continue
                types = candidate.get("@type")
                type_names = types if isinstance(types, list) else [types]
                if "JobPosting" in type_names:
                    return candidate
        raise ValueError("На странице Хабр Карьеры не найдены данные вакансии")

    @staticmethod
    def _format_detail_habr_salary(value: object) -> str:
        if not isinstance(value, dict):
            return "не указана"
        amount = value.get("value")
        currency = value.get("currency") or ""
        if isinstance(amount, dict):
            minimum = amount.get("minValue")
            maximum = amount.get("maxValue")
            if minimum is not None and maximum is not None:
                text = f"{minimum}–{maximum}"
            elif minimum is not None:
                text = f"от {minimum}"
            elif maximum is not None:
                text = f"до {maximum}"
            else:
                text = amount.get("value")
        else:
            text = amount
        if text in (None, ""):
            return "не указана"
        return f"{text} {currency}".strip()

    @staticmethod
    def _format_detail_habr_location(value: object) -> str:
        locations = value if isinstance(value, list) else [value]
        names: list[str] = []
        for location in locations:
            if not isinstance(location, dict):
                continue
            address = location.get("address") or {}
            if not isinstance(address, dict):
                continue
            name = (
                address.get("addressLocality")
                or address.get("streetAddress")
                or address.get("addressRegion")
            )
            if name and name not in names:
                names.append(str(name))
        return ", ".join(names) or "—"

    @classmethod
    def _format_detail_habr_skills(cls, value: object) -> list[str]:
        if isinstance(value, list):
            return [cls._clean_html(item) for item in value if cls._clean_html(item)]
        if isinstance(value, str):
            return [
                item.strip()
                for item in re.split(r"[,;]", cls._clean_html(value))
                if item.strip()
            ]
        return []

    async def parse_vacancy(self, url: str) -> dict:
        """Парсит одну вакансию career.habr.com через браузер Playwright."""
        vacancy_id = self._vacancy_id_from_url(
            url,
            allowed_hosts={"career.habr.com"},
            path_pattern=r"/vacancies/(\d+)",
        )
        canonical_url = f"https://career.habr.com/vacancies/{vacancy_id}"
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            context = await browser.new_context(
                locale="ru-RU",
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/125.0.0.0 Safari/537.36"
                ),
            )
            page = await context.new_page()
            try:
                await self._goto_with_retry(page, canonical_url)
                await page.wait_for_load_state("domcontentloaded")
                page_html = await page.content()
            finally:
                await context.close()
                await browser.close()

        data = self._extract_job_posting(page_html)
        organization = data.get("hiringOrganization") or {}
        company = organization.get("name") if isinstance(organization, dict) else None
        return {
            "source": "habr",
            "external_id": vacancy_id,
            "title": data.get("title") or data.get("name") or "—",
            "company": company or "—",
            "salary": self._format_detail_habr_salary(data.get("baseSalary")),
            "city": self._format_detail_habr_location(data.get("jobLocation")),
            "schedule": self._clean_html(data.get("jobLocationType")) or "—",
            "employment": self._clean_html(data.get("employmentType")) or "—",
            "experience": (self._clean_html(data.get("experienceRequirements")) or "—"),
            "skills": self._format_detail_habr_skills(data.get("skills")),
            "description": self._clean_html(data.get("description")),
            "published_at": data.get("datePosted"),
            "link": data.get("url") or canonical_url,
        }

    @staticmethod
    def _salary_numbers(salary: str) -> list[int]:
        return [
            int(re.sub(r"\s|\u202f", "", num_str))
            for num_str in re.findall(r"[\d][\d\s\u202f]*[\d]|[\d]+", salary)
            if re.sub(r"\s|\u202f", "", num_str).isdigit()
        ]

    def _apply_filters(self, data: list[dict]) -> list[dict]:
        """Применяет общие и Habr-специфичные пост-фильтры."""
        result = super()._apply_filters(data)
        filters = self.filters

        if filters.only_with_salary:
            before = len(result)
            result = [
                vacancy
                for vacancy in result
                if vacancy["salary"] and vacancy["salary"] != "не указана"
            ]
            logger.info(f"  only_with_salary:  {before} → {len(result)}")

        if filters.salary_from:
            before = len(result)
            result = [
                vacancy
                for vacancy in result
                if (
                    vacancy["salary"] != "не указана"
                    and self._salary_numbers(vacancy["salary"])
                    and max(self._salary_numbers(vacancy["salary"]))
                    >= filters.salary_from
                )
            ]
            logger.info(f"  salary_from:       {before} → {len(result)}")

        if filters.schedule:
            before = len(result)
            requested_schedules = set(filters.schedule)

            def schedule_matches(vacancy: dict) -> bool:
                schedule = vacancy["schedule"].lower()
                if "remote" in requested_schedules and "удал" in schedule:
                    return True
                if "fullDay" in requested_schedules and "удал" not in schedule:
                    return True
                return False

            result = [vacancy for vacancy in result if schedule_matches(vacancy)]
            logger.info(f"  schedule:          {before} → {len(result)}")

        if filters.employment:
            before = len(result)
            employment_markers = {
                "full": "полная",
                "part": "частичная",
                "project": "проект",
                "probation": "стаж",
            }
            requested_markers = [
                employment_markers[employment]
                for employment in filters.employment
                if employment in employment_markers
            ]
            if requested_markers:
                result = [
                    vacancy
                    for vacancy in result
                    if any(
                        marker in vacancy["schedule"].lower()
                        for marker in requested_markers
                    )
                ]
                logger.info(f"  employment:        {before} → {len(result)}")

        return result

    async def _fetch_html(self, session: aiohttp.ClientSession, url: str) -> str:
        async with session.get(url) as response:
            response.raise_for_status()
            return await response.text()

    async def _search_via_ssr(
        self, session: aiohttp.ClientSession, query: str
    ) -> list[dict]:
        all_results: list[dict] = []

        for page_num in range(self.max_pages):
            url = self._build_url(query, page_num)
            logger.info("  ↳ страница %d", page_num + 1)

            if page_num > 0:
                await asyncio.sleep(self.BETWEEN_PAGES_DELAY)

            try:
                page_html = await self._fetch_html(session, url)
            except Exception:
                logger.error("    [!] Ошибка загрузки страницы Habr")
                break

            state = self._extract_ssr_state(page_html)
            vacancies_block = state.get("vacancies") or {}
            page_vacancies = [
                self._vacancy_from_habr_json(vacancy)
                for vacancy in vacancies_block.get("list", [])
                if isinstance(vacancy, dict)
            ]

            if not page_vacancies:
                logger.info("    [!] Нет результатов — стоп")
                break

            for vacancy in page_vacancies:
                vacancy["query"] = query
            all_results.extend(page_vacancies)
            logger.info(f"    ✓ найдено: {len(page_vacancies)}")

            meta = vacancies_block.get("meta") or {}
            total_pages = meta.get("totalPages")
            if isinstance(total_pages, int) and page_num + 1 >= total_pages:
                break

        return all_results

    async def run_parser(self) -> list[dict]:
        logger.info("=" * 60)
        logger.info("  Career Habr Parser")
        logger.info("  Количество запросов: %d", len(self.search_queries))
        logger.info("  Страниц на запрос: %d", self.max_pages)
        self._log_filters()
        logger.info("=" * 60)

        all_vacancies: list[dict] = []

        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
        }
        timeout = aiohttp.ClientTimeout(total=60)

        async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
            for query_index, query in enumerate(self.search_queries, start=1):
                logger.info("[→] Запрос %d/%d", query_index, len(self.search_queries))
                results = await self._search_via_ssr(session, query)
                all_vacancies.extend(results)
                logger.info(f"    Итого: {len(results)}")
                await asyncio.sleep(2.0)

        unique_vacancies = self.deduplicate(all_vacancies)
        logger.info(f"\n{'─' * 60}")
        logger.info(f"Уникальных вакансий (до пост-фильтров): {len(unique_vacancies)}")

        filtered_vacancies = self._apply_filters(unique_vacancies)
        logger.info(
            f"Уникальных вакансий (после пост-фильтров): {len(filtered_vacancies)}"
        )
        logger.info(f"{'─' * 60}")

        if self.save_to_json:
            self.save_json(filtered_vacancies)
        if self.save_to_csv:
            self.save_csv(filtered_vacancies)

        logger.info(f"\n{'─' * 60}")
        logger.info("Результатов для выдачи: %d", len(filtered_vacancies))
        logger.info(f"{'─' * 60}")

        return filtered_vacancies
