import tempfile
import unittest
from pathlib import Path

from backend.isolated_document_reader import read_document_isolated


class IsolatedDocumentReaderTests(unittest.TestCase):
    def test_reads_text_in_disposable_process(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "resume.txt"
            path.write_text("Python developer", encoding="utf-8")
            self.assertEqual(read_document_isolated(path), "Python developer")


if __name__ == "__main__":
    unittest.main()
