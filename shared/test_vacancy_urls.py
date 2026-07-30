import unittest

from shared.vacancy_urls import safe_vacancy_url, validate_vacancy_url


class VacancyUrlTests(unittest.TestCase):
    def test_accepts_and_canonicalizes_supported_urls(self) -> None:
        cases = {
            "https://hh.ru/vacancy/123?from=search#top": (
                "https://hh.ru/vacancy/123",
                "hh",
            ),
            "https://spb.hh.ru/vacancy/456/": (
                "https://hh.ru/vacancy/456",
                "hh",
            ),
            "https://career.habr.com/vacancies/789": (
                "https://career.habr.com/vacancies/789",
                "habr",
            ),
        }
        for raw_url, expected in cases.items():
            with self.subTest(raw_url=raw_url):
                result = validate_vacancy_url(raw_url)
                self.assertEqual((result.url, result.source), expected)

    def test_rejects_unsafe_scheme_hostname_and_path(self) -> None:
        unsafe_urls = (
            "http://hh.ru/vacancy/123",
            "javascript:alert(1)",
            "https://hh.ru.evil.example/vacancy/123",
            "https://career.habr.com.evil.example/vacancies/123",
            "https://user:password@hh.ru/vacancy/123",
            "https://hh.ru:8443/vacancy/123",
            "https://hh.ru/employer/123",
            "https://career.habr.com/vacancies/not-a-number",
            "https://hh.ru/vacancy/123/../../admin",
        )
        for raw_url in unsafe_urls:
            with self.subTest(raw_url=raw_url):
                with self.assertRaises(ValueError):
                    validate_vacancy_url(raw_url)
                self.assertIsNone(safe_vacancy_url(raw_url))


if __name__ == "__main__":
    unittest.main()
