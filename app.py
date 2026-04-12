from __future__ import annotations

from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_from_directory

from core import date_engine, errors, registry, renderer, session_manager, template_manager
from core.session_manager import Session
from core.utils import build_session_storage_name, normalize_filename, normalize_session_name

# Локальное веб‑приложение для генерации комплектов исполнительной документации.
# Детали бизнес‑логики реализуются в модулях core/*.


BASE_DIR = Path(__file__).resolve().parent
RU_MONTHS_GEN = {
    1: "января",
    2: "февраля",
    3: "марта",
    4: "апреля",
    5: "мая",
    6: "июня",
    7: "июля",
    8: "августа",
    9: "сентября",
    10: "октября",
    11: "ноября",
    12: "декабря",
}


def _parse_any_date(value):
    if not value:
        return None
    v = str(value).strip()
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(v, fmt)
        except ValueError:
            continue
    return None


def _augment_doc_context(context: dict, doc: dict) -> dict:
    """Добавляет производные поля для шаблонов АОСР по логике Nik66."""
    start_dt = _parse_any_date(context.get("Начало")) or _parse_any_date(doc.get("start_date"))
    end_dt = _parse_any_date(context.get("Конец")) or _parse_any_date(doc.get("end_date"))

    if start_dt:
        context.setdefault("Начало", start_dt.strftime("%d.%m.%Y"))
        context["Чнач"] = str(start_dt.day)
        context["Мнач"] = RU_MONTHS_GEN.get(start_dt.month, "")
        context["Гн"] = str(start_dt.year)
    if end_dt:
        context.setdefault("Конец", end_dt.strftime("%d.%m.%Y"))
        context["Ч"] = str(end_dt.day)
        context["М"] = RU_MONTHS_GEN.get(end_dt.month, "")
        context["Г"] = str(end_dt.year)
        context["date_end"] = end_dt.strftime("%Y-%m-%d")

    # Совместимость с коротким плейсхолдером из старого шаблона.
    if context.get("Разрешает_пр_во_работ_по") and not context.get("Разрешает_пр"):
        context["Разрешает_пр"] = context.get("Разрешает_пр_во_работ_по")

    return context


def create_app() -> Flask:
    """Фабрика Flask‑приложения.

    Здесь настраиваются:
    - конфигурация;
    - регистрация маршрутов;
    - инициализация логирования.
    """
    errors.setup_logging()

    app = Flask(
        __name__,
        static_folder=str(BASE_DIR / "static"),
        template_folder=str(BASE_DIR / "templates_web"),
    )
    # Важно: не сортируем ключи JSON, чтобы сохранять порядок полей шаблона.
    app.config["JSON_SORT_KEYS"] = False
    try:
        app.json.sort_keys = False
    except Exception:
        pass

    # Главная страница — HTML UI
    @app.get("/")
    def index():
        return render_template("index.html")

    # Отдача примерных сессий (для фронтенда)
    @app.get("/sessions/<path:filename>")
    def get_session_file(filename: str):
        return send_from_directory(BASE_DIR / "sessions", filename, as_attachment=False)

    @app.get("/tmp_previews/<session_name>/<path:filename>")
    def get_preview_file(session_name: str, filename: str):
        """Отдача сгенерированных preview PDF для встроенного viewer."""
        safe_session = normalize_filename(session_name)
        return send_from_directory(BASE_DIR / "tmp_previews" / safe_session, filename, as_attachment=False)

    # --- Сессии ------------------------------------------------------------

    @app.post("/api/session/load")
    def api_load_session():
        """Загрузить сессию по имени / пути.

        Ожидаемый JSON:
        {
          "name": "Объект_123_v1_20250201"
        }
        """
        data = request.get_json(silent=True) or {}
        name = data.get("name")
        if not name:
            return jsonify({"error": "Field 'name' is required"}), 400
        normalized = normalize_session_name(name)
        candidates = [normalized]
        storage_candidate = build_session_storage_name(normalized)
        if storage_candidate not in candidates:
            candidates.append(storage_candidate)

        sess = None
        for candidate in candidates:
            try:
                sess = session_manager.load_session(candidate)
                break
            except FileNotFoundError:
                continue
            except Exception as e:  # pragma: no cover - защитный код
                errors.handle_error(e, {"endpoint": "api_load_session"})
                return jsonify({"error": "Failed to load session"}), 500
        if sess is None:
            return jsonify({"error": "Session not found", "name": name}), 404

        return jsonify(sess.raw)

    @app.post("/api/session/save")
    def api_save_session():
        """Сохранить сессию.

        Ожидаемый JSON:
        {
          "session": { ... полная структура session.json ... },
          "name": "опционально, имя файла без .json"
        }
        """
        payload = request.get_json(silent=True) or {}
        session_data = payload.get("session")
        name = payload.get("name")
        if not isinstance(session_data, dict):
            return jsonify({"error": "Field 'session' must be object"}), 400

        try:
            sess = Session(raw=session_data)
            if name:
                name = normalize_session_name(name)
                name = build_session_storage_name(name)
            path = session_manager.save_session(sess, name=name)
        except Exception as e:  # pragma: no cover
            errors.handle_error(e, {"endpoint": "api_save_session"})
            return jsonify({"error": "Failed to save session"}), 500

        return jsonify({"status": "ok", "path": str(path), "name": path.stem})

    @app.get("/api/session/list")
    def api_list_sessions():
        """Список сохраненных сессий (имена файлов без .json)."""
        try:
            names = session_manager.list_sessions()
        except Exception as e:  # pragma: no cover
            errors.handle_error(e, {"endpoint": "api_list_sessions"})
            return jsonify({"error": "Failed to list sessions"}), 500
        return jsonify(names)

    @app.get("/api/session/list")
    def api_list_sessions():
        """Вернуть список сохранённых сессий."""
        try:
            names = session_manager.list_sessions()
        except Exception as e:  # pragma: no cover
            errors.handle_error(e, {"endpoint": "api_list_sessions"})
            return jsonify({"error": "Failed to list sessions"}), 500
        return jsonify({"items": names})

    @app.get("/api/session/list")
    def api_list_sessions():
        """Вернуть список сохранённых сессий."""
        try:
            names = session_manager.list_sessions()
        except Exception as e:  # pragma: no cover
            errors.handle_error(e, {"endpoint": "api_list_sessions"})
            return jsonify({"error": "Failed to list sessions"}), 500
        return jsonify({"items": names})

    # --- Даты --------------------------------------------------------------

    @app.post("/api/dates/calculate")
    def api_calculate_dates():
        """Пересчитать даты документов в сессии.

        Ожидаемый JSON:
        {
          "session": { ... },
          "global_start": "2025-10-01",
          "global_end": "2025-10-31"
        }
        """
        payload = request.get_json(silent=True) or {}
        session_data = payload.get("session")
        if not isinstance(session_data, dict):
            return jsonify({"error": "Field 'session' must be object"}), 400

        global_start = payload.get("global_start")
        global_end = payload.get("global_end")

        # Пока делегируем в core.date_engine.distribute_dates без деталей алгоритма;
        # сам алгоритм будет доработан отдельно.
        try:
            updated = date_engine.distribute_dates(session_data, global_start, global_end)
        except Exception as e:  # pragma: no cover
            errors.handle_error(e, {"endpoint": "api_calculate_dates"})
            return jsonify({"error": "Failed to calculate dates"}), 500

        return jsonify(updated)

    # --- Генерация документов ----------------------------------------------

    @app.post("/api/generate")
    def api_generate_documents():
        """Сгенерировать все документы (docx + pdf) и, опционально, общий PDF."""
        payload = request.get_json(silent=True) or {}
        session_data = payload.get("session")
        merge_pdf = bool(payload.get("merge_pdf", False))

        if not isinstance(session_data, dict):
            return jsonify({"error": "Field 'session' must be object"}), 400

        sess = Session(raw=session_data)
        session_name = normalize_filename(sess.name)
        output_root = BASE_DIR / "output" / session_name

        docs = registry.build_registry(sess.raw)
        generated = []
        pdf_paths = []

        for doc in docs:
            template_name = doc.get("template")
            if not template_name:
                continue
            template_path = BASE_DIR / "templates" / template_name

            order = doc.get("order", 0)
            doc_type = doc.get("type", "DOC")
            title = doc.get("title", template_path.stem)

            short = normalize_filename(title, max_length=50)
            filename_base = f"{order:02d}_{doc_type}_{short}"

            out_docx = output_root / f"{filename_base}.docx"
            out_pdf = output_root / f"{filename_base}.pdf"

            context = {}
            context.update(sess.raw.get("constant_fields") or {})
            context.update(doc.get("data") or {})
            context = _augment_doc_context(context, doc)

            try:
                renderer.render_docx(template_path, context, out_docx)
                renderer.convert_to_pdf(out_docx, out_pdf)
            except Exception as e:  # pragma: no cover
                errors.handle_error(e, {"endpoint": "api_generate_documents", "doc_id": doc.get("id")})
                continue

            generated.append(
                {
                    "id": doc.get("id"),
                    "docx": str(out_docx),
                    "pdf": str(out_pdf),
                }
            )
            pdf_paths.append(out_pdf)

        merged_pdf_path = None
        if merge_pdf and pdf_paths:
            try:
                merged_pdf_path = output_root / "merged.pdf"
                renderer.merge_pdfs(pdf_paths, merged_pdf_path)
            except Exception as e:  # pragma: no cover
                errors.handle_error(e, {"endpoint": "api_generate_documents", "action": "merge_pdfs"})

        return jsonify(
            {
                "status": "ok",
                "documents": generated,
                "merged_pdf": str(merged_pdf_path) if merged_pdf_path else None,
            }
        )

    @app.post("/api/preview")
    def api_preview_document():
        """Сгенерировать pdf‑предпросмотр одного документа."""
        payload = request.get_json(silent=True) or {}
        session_data = payload.get("session")
        doc_id = payload.get("doc_id")

        if not isinstance(session_data, dict):
            return jsonify({"error": "Field 'session' must be object"}), 400
        if not doc_id:
            return jsonify({"error": "Field 'doc_id' is required"}), 400

        sess = Session(raw=session_data)
        session_name = normalize_filename(sess.name)
        previews_root = BASE_DIR / "tmp_previews" / session_name

        docs = registry.build_registry(sess.raw)
        target_doc = next((d for d in docs if d.get("id") == doc_id), None)
        if not target_doc:
            return jsonify({"error": "Document not found", "doc_id": doc_id}), 404

        template_name = target_doc.get("template")
        if not template_name:
            return jsonify({"error": "Template not specified for document", "doc_id": doc_id}), 400

        template_path = BASE_DIR / "templates" / template_name
        short = normalize_filename(target_doc.get("title") or template_path.stem, max_length=50)
        filename_base = f"preview_{short}"

        out_docx = previews_root / f"{filename_base}.docx"
        out_pdf = previews_root / f"{filename_base}.pdf"

        context = {}
        context.update(sess.raw.get("constant_fields") or {})
        context.update(target_doc.get("data") or {})
        context = _augment_doc_context(context, target_doc)

        try:
            renderer.render_docx(template_path, context, out_docx)
            renderer.convert_to_pdf(out_docx, out_pdf)
        except Exception as e:  # pragma: no cover
            errors.handle_error(e, {"endpoint": "api_preview_document", "doc_id": doc_id})
            return jsonify({"error": "Failed to generate preview"}), 500

        preview_url = f"/tmp_previews/{session_name}/{out_pdf.name}"
        return jsonify({"status": "ok", "pdf": str(out_pdf), "preview_url": preview_url})

    # --- Шаблоны ------------------------------------------------------------

    @app.get("/api/templates/list")
    def api_templates_list():
        """Вернуть список шаблонов .docx и их metadata (если есть)."""
        metas = template_manager.scan_templates(BASE_DIR / "templates")
        result = []
        for meta in metas:
            docx_path = meta.path
            json_path = docx_path.with_suffix(".json")
            result.append(
                {
                    "docx_name": docx_path.name,
                    "json_name": json_path.name if json_path.exists() else None,
                    "has_metadata": json_path.exists(),
                    "metadata": meta.to_dict() if json_path.exists() else None,
                }
            )
        return jsonify(result)

    @app.post("/api/templates/build_metadata")
    def api_build_metadata():
        """Автогенерация metadata по .docx без сохранения в файл.

        Ожидаемый JSON:
        {
          "template_name": "01_AOSR.docx"
        }
        """
        payload = request.get_json(silent=True) or {}
        name = payload.get("template_name")
        if not name:
            return jsonify({"error": "Field 'template_name' is required"}), 400

        docx_path = BASE_DIR / "templates" / name
        if not docx_path.exists():
            return jsonify({"error": "Template .docx not found", "template_name": name}), 404

        try:
            meta = template_manager.build_metadata_skeleton(docx_path)
        except Exception as e:  # pragma: no cover
            errors.handle_error(e, {"endpoint": "api_build_metadata", "template_name": name})
            return jsonify({"error": "Failed to build metadata"}), 500

        return jsonify({"status": "ok", "template_name": name, "metadata": meta.to_dict()})

    @app.post("/api/templates/save_metadata")
    def api_save_metadata():
        """Сохранить metadata в template.json.

        Ожидаемый JSON:
        {
          "template_name": "01_AOSR.docx",
          "metadata": { ... содержимое template.json ... }
        }
        """
        payload = request.get_json(silent=True) or {}
        name = payload.get("template_name")
        metadata = payload.get("metadata")
        if not name:
            return jsonify({"error": "Field 'template_name' is required"}), 400
        if not isinstance(metadata, dict):
            return jsonify({"error": "Field 'metadata' must be object"}), 400

        docx_path = BASE_DIR / "templates" / name
        if not docx_path.exists():
            return jsonify({"error": "Template .docx not found", "template_name": name}), 404

        # Строим объект TemplateMeta, чтобы структура была валидной.
        meta = template_manager.load_template_metadata_from_dict(docx_path, metadata)
        if meta is None:
            return jsonify({"error": "Invalid metadata structure"}), 400

        try:
            json_path = template_manager.save_template_metadata(meta)
        except Exception as e:  # pragma: no cover
            errors.handle_error(e, {"endpoint": "api_save_metadata", "template_name": name})
            return jsonify({"error": "Failed to save metadata"}), 500

        return jsonify({"status": "ok", "json_path": str(json_path)})

    return app


if __name__ == "__main__":
    # Запуск для локальной разработки
    flask_app = create_app()
    flask_app.run(host="127.0.0.1", port=5000, debug=True)
