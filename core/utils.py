"""
Общие вспомогательные функции.

На основании спецификации сюда будут вынесены:
- нормализация имён файлов;
- функции форматирования и парсинга дат;
- прочие небольшие хелперы, не завязанные на Flask.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Iterable


FILENAME_SAFE_PATTERN = re.compile(r"[^\w\s.-]+", flags=re.UNICODE)


def normalize_filename(value: str, max_length: int = 100) -> str:
    """Превращает произвольную строку в безопасное имя файла.

    Пример: "Объект 1: труба Ø110" -> "Obekt_1_truba_110".
    Реализация черновая; при необходимости дорабатывается.
    """
    if not value:
        return "file"

    # Сохраняем unicode-буквы/цифры и безопасные разделители, пробелы заменяем на "_".
    cleaned = FILENAME_SAFE_PATTERN.sub("_", value.strip())
    cleaned = re.sub(r"\s+", "_", cleaned)
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    if not cleaned:
        cleaned = "file"
    return cleaned[:max_length]


def normalize_session_name(value: str, max_length: int = 120) -> str:
    """Нормализация имени сессии с сохранением читаемого формата.

    В отличие от normalize_filename, здесь сохраняются пробелы, точки и
    национальные символы (например, кириллица), чтобы имя в UI и на диске
    выглядело одинаково: "тест1 21.03.2026 20:03".
    """
    raw = str(value or "").strip()
    if not raw:
        return "session"

    # На Windows запрещены: <>:"/\|?* и управляющие символы.
    cleaned = SESSION_FORBIDDEN_PATTERN.sub("_", raw)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    # Имя файла не должно заканчиваться точкой или пробелом.
    cleaned = cleaned.rstrip(" .")
    if not cleaned:
        cleaned = "session"
    return cleaned[:max_length]


def build_session_storage_name(display_name: str, max_length: int = 160) -> str:
    """Преобразует отображаемое имя в сортируемое имя файла.

    Пример:
    - display: "тест1 21.03.2026 20:03"
    - storage: "тест1__2026-03-21__20-03"
    """
    display = normalize_session_name(display_name, max_length=max_length)
    m = DISPLAY_STAMP_PATTERN.match(display)
    if not m:
        return display

    base = normalize_session_name(m.group("base"), max_length=max_length)
    yyyy = m.group("yyyy")
    mm = m.group("mm")
    dd = m.group("dd")
    hh = m.group("hh")
    mi = m.group("mi")
    storage = f"{base}__{yyyy}-{mm}-{dd}__{hh}-{mi}"
    return normalize_session_name(storage, max_length=max_length)


def parse_iso_date(value: str | None) -> date | None:
    """Парсинг даты в ISO‑формате YYYY-MM-DD. При ошибке возвращает None."""
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def format_iso_date(d: date | None) -> str | None:
    """Форматирование даты в ISO‑строку YYYY-MM-DD."""
    if d is None:
        return None
    return d.strftime("%Y-%m-%d")


def format_display_date(d: date | None) -> str | None:
    """Форматирование даты для отображения в UI: DD.MM.YYYY."""
    if d is None:
        return None
    return d.strftime("%d.%m.%Y")


def chunked(iterable: Iterable, size: int):
    """Разбиение последовательности на чанки фиксированного размера.

    Удобно для распределения рабочих дней между документами.
    """
    if size <= 0:
        raise ValueError("size must be > 0")
    chunk = []
    for item in iterable:
        chunk.append(item)
        if len(chunk) >= size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk
