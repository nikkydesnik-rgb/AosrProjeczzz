"""
Логирование и обработка ошибок.

См. раздел 14 спецификации:
- app.log / error.log;
- формат сообщений;
- дружественные уведомления для UI.

Сейчас реализована базовая настройка logging и функция handle_error().
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any


LOGS_DIR = Path("logs")


def setup_logging(level: int = logging.INFO) -> None:
    """Инициализирует файловые логеры app.log и error.log."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root = logging.getLogger()
    if root.handlers:
        # Уже настроено
        return

    root.setLevel(level)

    app_handler = logging.FileHandler(LOGS_DIR / "app.log", encoding="utf-8")
    app_handler.setLevel(level)
    app_handler.setFormatter(formatter)

    err_handler = logging.FileHandler(LOGS_DIR / "error.log", encoding="utf-8")
    err_handler.setLevel(logging.ERROR)
    err_handler.setFormatter(formatter)

    console = logging.StreamHandler()
    console.setLevel(level)
    console.setFormatter(formatter)

    root.addHandler(app_handler)
    root.addHandler(err_handler)
    root.addHandler(console)


def handle_error(e: BaseException, context: dict | None = None) -> None:
    """Логирует исключение с дополнительным контекстом."""
    logger = logging.getLogger("core.errors")
    extra: dict[str, Any] = {"context": context or {}}
    logger.exception("Unhandled error: %s", e, extra=extra)

