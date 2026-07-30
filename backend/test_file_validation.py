import io
import unittest
import zipfile

from backend.file_validation import validate_resume_file


def _docx_bytes(*, include_document: bool = True, include_macro: bool = False) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types />")
        if include_document:
            archive.writestr("word/document.xml", "<document />")
        if include_macro:
            archive.writestr("word/vbaProject.bin", b"macro")
    return output.getvalue()


def _docx_with_traversal() -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types />")
        archive.writestr("word/document.xml", "<document />")
        archive.writestr("../outside.xml", "<outside />")
    return output.getvalue()


class ResumeFileValidationTests(unittest.TestCase):
    def test_detects_supported_signatures(self) -> None:
        cases = (
            (b"%PDF-1.7\nbody", "cv.pdf", ".pdf"),
            (_docx_bytes(), "cv.docx", ".docx"),
            (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1payload", "cv.doc", ".doc"),
            ("Резюме\nPython".encode(), "cv.txt", ".txt"),
        )
        for content, filename, expected_extension in cases:
            with self.subTest(filename=filename):
                result = validate_resume_file(io.BytesIO(content), filename)
                self.assertEqual(result.extension, expected_extension)

    def test_rejects_extension_spoofing_and_binary_as_text(self) -> None:
        cases = (
            (b"%PDF-1.7\nbody", "cv.txt"),
            (b"\x00\x01\x02executable", "cv.txt"),
            (b"MZ\x90\x00executable", "cv.pdf"),
            (_docx_bytes(include_document=False), "cv.docx"),
            (_docx_bytes(include_macro=True), "cv.docx"),
            (_docx_with_traversal(), "cv.docx"),
        )
        for content, filename in cases:
            with self.subTest(filename=filename):
                with self.assertRaises(ValueError):
                    validate_resume_file(io.BytesIO(content), filename)


if __name__ == "__main__":
    unittest.main()
