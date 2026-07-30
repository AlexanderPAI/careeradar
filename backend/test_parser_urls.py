import unittest

from backend.utils.parser import HHParser
from shared.vacancy_urls import validate_vacancy_url


class ParserUrlTests(unittest.TestCase):
    def test_normalizes_relative_hh_card_url_before_final_validation(self) -> None:
        normalized = HHParser._normalize_search_result_url(
            "/vacancy/123456?from=vacancy_search_list"
        )

        self.assertEqual(normalized, "https://hh.ru/vacancy/123456")
        self.assertEqual(validate_vacancy_url(normalized).source, "hh")

    def test_does_not_rebase_protocol_relative_external_url(self) -> None:
        normalized = HHParser._normalize_search_result_url(
            "//evil.example/vacancy/123456"
        )

        with self.assertRaises(ValueError):
            validate_vacancy_url(normalized)


if __name__ == "__main__":
    unittest.main()
