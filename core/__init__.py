"""
Пакет core — бизнес‑логика генератора исполнительной документации.

Содержит независимые от веб‑фреймворка модули:
- session_manager  — работа с session.json;
- template_manager — работа с шаблонами .docx и metadata (.json);
- renderer        — рендеринг .docx, конвертация в .pdf и merge;
- date_engine     — расчёт рабочих дней и распределение дат;
- material_engine — распределение материалов по актам;
- registry        — построение и обновление реестра документов;
- utils           — общие вспомогательные функции;
- errors          — логирование и обработка ошибок.

Каждый модуль должен быть по возможности чистым и легко тестируемым.
"""

from . import date_engine, errors, material_engine, registry, renderer, session_manager, template_manager, utils

__all__ = [
    "date_engine",
    "errors",
    "material_engine",
    "registry",
    "renderer",
    "session_manager",
    "template_manager",
    "utils",
]

