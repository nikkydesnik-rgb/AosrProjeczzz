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
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List


SESSIONS_DIR = Path("sessions")
SESSION_DEFAULTS: Dict[str, Any] = {
    "meta": {
        "session_id": "",
        "name": "unnamed_session",
    },
    "constant_fields": {},
    "documents": [],
    "materials": [],
    "attachments": [],
    "registry_rows": [],
    "settings": {},
}


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


def get_session_path(name: str) -> Path:
    """Возвращает путь к файлу сессии по имени без расширения."""
    base = _ensure_sessions_dir()
    return base / f"{name}.json"


def new_session(name: str) -> Session:
    """Создаёт новую пустую сессию с минимальными полями meta."""
    data: Dict[str, Any] = coerce_session_dict({})
    data["meta"]["name"] = name
    return Session(raw=data)


def coerce_session_dict(raw: Dict[str, Any] | None) -> Dict[str, Any]:
    """Нормализует словарь сессии до минимально ожидаемой структуры."""
    source = raw if isinstance(raw, dict) else {}
    data = deepcopy(SESSION_DEFAULTS)
    data.update({k: v for k, v in source.items() if k in data})
    if not isinstance(data.get("meta"), dict):
        data["meta"] = deepcopy(SESSION_DEFAULTS["meta"])
    meta = data["meta"]
    meta.setdefault("session_id", "")
    meta.setdefault("name", "unnamed_session")
    return data


def load_session(name_or_path: str) -> Session:
    """Загружает сессию по имени (без .json) или полному пути."""
    path = Path(name_or_path)
    if not path.suffix:
        path = get_session_path(name_or_path)

    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return Session(raw=coerce_session_dict(data))


def save_session(session: Session, name: str | None = None) -> Path:
    """Сохраняет сессию в файл и возвращает путь.

    Если name не указан, используется session.name.
    """
    if name is None:
        name = session.name
    path = get_session_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    session.raw = coerce_session_dict(session.raw)
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
