"""
Модуль распределения рабочих дней и дат документов.

См. раздел 9 спецификации:
- get_workdays(start, end)          — список рабочих дат (по умолчанию пн‑пт);
- distribute_dates(session)        — равномерное распределение диапазона по документам;
- уважение флага manual_override;
- поддержка разных режимов дат (period / single).

Пока реализована только базовая вспомогательная логика get_workdays;
distribute_dates — заготовка под будущую реализацию.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable, List, Sequence


DEFAULT_WORKDAYS = {1, 2, 3, 4, 5}  # ISO: 1=понедельник ... 7=воскресенье


def get_workdays(start: date, end: date, workdays: Iterable[int] | None = None) -> List[date]:
    """Возвращает список рабочих дат между start и end включительно.

    workdays — множество номеров дней недели ISO (1..7).
    """
    if start > end:
        start, end = end, start

    workdays_set = set(workdays or DEFAULT_WORKDAYS)
    result: List[date] = []
    current = start
    while current <= end:
        if current.isoweekday() in workdays_set:
            result.append(current)
        current += timedelta(days=1)
    return result


def _get_workdays_from_settings(session: dict) -> Iterable[int]:
    settings = session.get("settings") or {}
    workdays = settings.get("workdays")
    if isinstance(workdays, (list, tuple, set)) and workdays:
        return [int(d) for d in workdays]
    return DEFAULT_WORKDAYS


def distribute_dates(session: dict, global_start: str | None, global_end: str | None) -> dict:
    """Распределяет даты документов внутри структуры session.

    Ожидается структура, совместимая со спецификацией session.json.
    Функция должна:
    - вычислить рабочие дни в глобальном диапазоне;
    - равномерно распределить их по документам;
    - для АОСР задать период (start_date / end_date);
    - для однодатных документов задать одну дату;
    - учитывать manual_override.

    global_start / global_end — строки в формате YYYY-MM-DD.
    """
    from core.utils import parse_iso_date, format_iso_date

    start_date = parse_iso_date(global_start)
    end_date = parse_iso_date(global_end)

    if not start_date or not end_date:
        # Если диапазон не задан — ничего не меняем.
        return session

    workdays_flags = _get_workdays_from_settings(session)
    all_days = get_workdays(start_date, end_date, workdays_flags)
    if not all_days:
        return session

    documents: List[dict] = list(session.get("documents") or [])
    # Сортировка по order — это же порядок в реестре.
    documents.sort(key=lambda d: d.get("order", 0))

    # Документы без manual_override участвуют в перерасчёте.
    docs_for_calc = [d for d in documents if not d.get("manual_override")]
    if not docs_for_calc:
        return session

    n_docs = len(docs_for_calc)
    n_days = len(all_days)

    # Распределяем блоки рабочих дней по документам.
    blocks: List[List[date]] = []

    if n_days >= n_docs:
        base = n_days // n_docs
        extra = n_days % n_docs

        idx = 0
        for i in range(n_docs):
            span = base + (1 if i < extra else 0)
            if span <= 0:
                span = 1
            block = all_days[idx : idx + span]
            if not block:
                block = [all_days[-1]]
            blocks.append(block)
            idx += span
    else:
        # Рабочих дней меньше, чем документов — допускаем наложения:
        # несколько документов могут иметь одну и ту же дату.
        for i in range(n_docs):
            day = all_days[i % n_days]
            blocks.append([day])

    # Применяем блоки к документам без manual_override.
    idx_block = 0
    for doc in documents:
        if doc.get("manual_override"):
            continue

        block = blocks[idx_block]
        idx_block += 1

        start = block[0]
        end = block[-1]

        doc_type = (doc.get("type") or "").strip()
        date_mode = doc.get("date_mode") or ("period" if doc_type == "АОСР" else "single")

        if date_mode == "period":
            doc["start_date"] = format_iso_date(start)
            doc["end_date"] = format_iso_date(end)
        else:
            single = end
            doc["start_date"] = format_iso_date(single)
            doc["end_date"] = format_iso_date(single)
            doc["date"] = format_iso_date(single)

        if idx_block >= len(blocks):
            # На всякий случай, если блоки закончились.
            idx_block = len(blocks) - 1

    # Специальный случай: "Освидетельствование сети"
    first_aosr = next((d for d in documents if (d.get("type") or "").strip() == "АОСР"), None)
    for i, doc in enumerate(documents):
        if (doc.get("type") or "").strip() == "Освидетельствование сети" and first_aosr:
            prev_doc = documents[i - 1] if i > 0 else first_aosr
            doc["start_date"] = first_aosr.get("start_date")
            doc["end_date"] = prev_doc.get("end_date") or first_aosr.get("end_date")

    return session

