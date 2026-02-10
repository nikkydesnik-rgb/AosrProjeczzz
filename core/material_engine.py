"""
Распределение материалов по актам и формирование текстовых блоков для шаблонов.

См. раздел 10 спецификации:
- структура строки materials;
- allocations: [{ "doc_id": "DOC_3", "qty": 100 }, ...];
- валидация суммы долей;
- формирование текстового представления для подстановки в шаблон.

Сейчас реализованы только простые заготовки.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class MaterialAllocation:
    doc_id: str
    qty: float


@dataclass
class MaterialRow:
    row_id: int
    name: str
    qty: float
    unit: str
    document_name: str | None = None
    validity: str | None = None
    allocations: List[MaterialAllocation] = field(default_factory=list)


def allocate_material(row: MaterialRow, allocations: List[MaterialAllocation]) -> None:
    """Присваивает материалу распределения по актам с простой проверкой суммы."""
    total = sum(a.qty for a in allocations)
    if total > row.qty + 1e-6:
        raise ValueError("Сумма распределений больше общего количества материала")
    row.allocations = allocations


def append_material_text_to_doc(doc: Dict, material: MaterialRow) -> None:
    """Добавляет текстовое описание материала в doc.data['Материалы_и_серты'].

    Ожидается, что doc имеет структуру из session['documents'][i].
    """
    data = doc.setdefault("data", {})
    key = "Материалы_и_серты"
    line = f"{material.name} — {material.qty:g} {material.unit}"
    if material.document_name:
        line += f" (документ: {material.document_name})"
    existing = data.get(key) or ""
    if existing:
        data[key] = existing.rstrip() + "; " + line
    else:
        data[key] = line

