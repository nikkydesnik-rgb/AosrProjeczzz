"""
Построение и обновление реестра документов.

См. раздел 8 спецификации:
- единый массив documents с полем order;
- возможность менять порядок (drag&drop);
- пересчёт номеров и использование их в именах файлов.

Здесь только базовые утилиты для сортировки и переназначения order.
"""

from __future__ import annotations

from typing import Dict, List


def build_registry(session: dict) -> List[Dict]:
    """Возвращает список документов, отсортированных по полю order."""
    docs = list(session.get("documents") or [])
    docs_sorted = sorted(docs, key=lambda d: d.get("order", 0))
    return docs_sorted


def update_order(session: dict, new_order: List[str]) -> None:
    """Перенумеровывает документы в session['documents'] согласно new_order.

    new_order — список document['id'] в желаемом порядке.
    """
    docs = session.get("documents") or []
    doc_by_id = {d.get("id"): d for d in docs}
    for idx, doc_id in enumerate(new_order, start=1):
        doc = doc_by_id.get(doc_id)
        if doc is not None:
            doc["order"] = idx

