from __future__ import annotations

from pathlib import Path

import pytest

import app as app_module
from core import session_manager, template_manager


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(session_manager, "SESSIONS_DIR", tmp_path / "sessions")
    flask_app = app_module.create_app()
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as test_client:
        yield test_client


def test_session_save_load_and_list(client):
    payload = {
        "session": {
            "meta": {"name": "demo"},
            "documents": [],
        },
        "name": "demo_session",
    }
    save_res = client.post("/api/session/save", json=payload)
    assert save_res.status_code == 200
    save_body = save_res.get_json()
    assert save_body["status"] == "ok"

    list_res = client.get("/api/session/list")
    assert list_res.status_code == 200
    items = list_res.get_json()["items"]
    assert "demo_session" in items

    load_res = client.post("/api/session/load", json={"name": "demo_session"})
    assert load_res.status_code == 200
    body = load_res.get_json()
    assert body["meta"]["name"] == "demo"
    assert "constant_fields" in body
    assert "materials" in body
    assert "attachments" in body
    assert "registry_rows" in body
    assert "settings" in body


def test_dates_calculate_endpoint_uses_engine(client, monkeypatch: pytest.MonkeyPatch):
    called = {}

    def fake_distribute(session_data, global_start, global_end):
        called["args"] = (session_data, global_start, global_end)
        return {"meta": {"name": "updated"}, "documents": []}

    monkeypatch.setattr(app_module.date_engine, "distribute_dates", fake_distribute)
    res = client.post(
        "/api/dates/calculate",
        json={"session": {"meta": {"name": "x"}}, "global_start": "2026-04-01", "global_end": "2026-04-10"},
    )
    assert res.status_code == 200
    assert res.get_json()["meta"]["name"] == "updated"
    assert called["args"][1] == "2026-04-01"
    assert called["args"][2] == "2026-04-10"


def test_templates_list_endpoint(client, monkeypatch: pytest.MonkeyPatch):
    meta = template_manager.TemplateMeta(
        path=Path("templates/01_AOSR.docx"),
        display_name="АОСР",
        type="АОСР",
    )

    monkeypatch.setattr(app_module.template_manager, "scan_templates", lambda _: [meta])
    res = client.get("/api/templates/list")
    assert res.status_code == 200
    data = res.get_json()
    assert isinstance(data, list)
    assert data[0]["docx_name"] == "01_AOSR.docx"

