import unittest

from backend.agents.searcher.agent import Agent


class SearcherFilterTests(unittest.TestCase):
    def test_discards_inferred_required_title_keywords(self) -> None:
        filters = {
            "schedule": ["remote"],
            "require_keywords": ["Python", "FastAPI", "Backend"],
        }

        result = Agent._sanitize_inferred_filters(
            filters,
            "Ищу удалённую работу Python-разработчиком на FastAPI",
        )

        self.assertEqual(result["require_keywords"], [])
        self.assertEqual(result["schedule"], ["remote"])

    def test_keeps_explicit_required_title_keywords(self) -> None:
        filters = {"require_keywords": ["Python"]}

        result = Agent._sanitize_inferred_filters(
            filters,
            "В названии обязательно должно быть слово Python",
        )

        self.assertEqual(result["require_keywords"], ["Python"])


if __name__ == "__main__":
    unittest.main()
