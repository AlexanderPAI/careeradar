from pathlib import Path

from langchain_core.tools import tool

from backend.isolated_document_reader import read_document_isolated


@tool
def extract_cv_text(cv_path: str) -> str:
    """
    Читает файл резюме и возвращает его текстовое содержимое.

    Args:
        cv_path: путь к файлу резюме (.txt, .pdf, .docx, .doc)

    Returns:
        Текст резюме в виде строки.
    """
    file_path = Path(cv_path)
    return read_document_isolated(file_path)
