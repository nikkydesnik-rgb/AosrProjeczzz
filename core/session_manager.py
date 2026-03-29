"""
Управление сессиями (session.json).

Согласно спецификации, одна сессия описывает один объект строительства
и содержит:
- meta;
- constant_fields;
- documents;
- materials;
- attachments;
- settings.

На этом этапе реализован только каркас с простыми операциями чтения/записи.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List


SESSIONS_DIR = Path("sessions")
SESSION_DATA_DIR = Path("session_data")


@dataclass
class Session:
    """Высокоуровневое представление session.json.

    Для простоты пока храним внутренности как словарь.
    При развитии проекта можно ввести отдельные dataclass для документов и т.п.
    """

    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def name(self) -> str:
        meta = self.raw.get("meta") or {}
        return meta.get("name") or "unnamed_session"


def _ensure_sessions_dir() -> Path:
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    return SESSIONS_DIR


def _ensure_session_data_dirs(session_name: str) -> Path:
    """Создаёт папки materials, attachments, exports для сессии.
    
    idempotent: безопасно вызывать несколько раз.
    """
    base = SESSION_DATA_DIR / session_name
    (base / "materials").mkdir(parents=True, exist_ok=True)
    (base / "attachments").mkdir(parents=True, exist_ok=True)
    (base / "exports").mkdir(parents=True, exist_ok=True)
    return base


def get_session_path(name: str) -> Path:
    """Возвращает путь к файлу сессии по имени без расширения."""
    base = _ensure_sessions_dir()
    return base / f"{name}.json"


def new_session(name: str) -> Session:
    """Создаёт новую пустую сессию с минимальными полями meta."""
    data: Dict[str, Any] = {
        "meta": {
            "session_id": "",
            "name": name,
        },
        "constant_fields": {},
        "documents": [],
        "materials": [],
        "attachments": [],
        "settings": {},
    }
    return Session(raw=data)


def load_session(name_or_path: str) -> Session:
    """Загружает сессию по имени (без .json) или полному пути."""
    path = Path(name_or_path)
    if not path.suffix:
        path = get_session_path(name_or_path)

    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return Session(raw=data)


def save_session(session: Session, name: str | None = None) -> Path:
    """Сохраняет сессию в файл и возвращает путь.

    При сохранении создаёт структуру папок:
    session_data/<session_name>/materials
    session_data/<session_name>/attachments
    session_data/<session_name>/exports
    """
    if name is None:
        name = session.name
    path = get_session_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    _ensure_session_data_dirs(name)
    with path.open("w", encoding="utf-8") as f:
        json.dump(session.raw, f, ensure_ascii=False, indent=2)
    return path


def list_sessions() -> List[str]:
    """Список доступных сессий (без расширения .json)."""
    base = _ensure_sessions_dir()
    result: List[str] = []
    for file in sorted(base.glob("*.json")):
        result.append(file.stem)
    return result

