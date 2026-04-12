import io
import re
import os
import base64
import zipfile
import unicodedata
import json
import uuid
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Tuple

from flask import Flask, request, send_file, render_template_string, flash, redirect, url_for, session, jsonify
from docxtpl import DocxTemplate
from docx2pdf import convert as docx2pdf_convert  # Requires Windows + Microsoft Word
import pythoncom
import pandas as pd
try:
    from pypdf import PdfWriter
    PDF_MERGER_AVAILABLE = True
except ImportError:
    try:
        from PyPDF2 import PdfMerger
        PDF_MERGER_AVAILABLE = True
    except ImportError:
        PDF_MERGER_AVAILABLE = False

# --- Flask app ---
app = Flask(__name__)
app.secret_key = "secret123"

# --- Constants and utilities ---
RU_MONTHS_GEN = {
    1: "января", 2: "февраля", 3: "марта", 4: "апреля", 5: "мая", 6: "июня",
    7: "июля", 8: "августа", 9: "сентября", 10: "октября", 11: "ноября", 12: "декабря"
}

def normalize_filename(name: str) -> str:
    name = unicodedata.normalize("NFKD", str(name))
    name = re.sub(r"[^\w\s\-\._]", "", name, flags=re.UNICODE)
    name = re.sub(r"\s+", "_", name).strip("_")
    return name[:120]

def bdays_range(start_date: datetime, end_date: datetime) -> List[datetime]:
    if end_date < start_date:
        start_date, end_date = end_date, start_date
    days = []
    cur = start_date
    while cur <= end_date:
        if cur.weekday() < 5:
            days.append(cur)
        cur += pd.Timedelta(days=1)
    return days

def split_business_days(days: List[datetime], segments: int) -> List[Tuple[datetime, datetime]]:
    if segments <= 0:
        return []
    if len(days) == 0:
        return [(None, None)] * segments
    base = len(days) // segments
    extra = len(days) % segments
    chunk_sizes = [base + (1 if i < extra else 0) for i in range(segments)]
    bounds, idx = [], 0
    for sz in chunk_sizes:
        if sz == 0:
            bounds.append((None, None))
        else:
            bounds.append((days[idx], days[idx + sz - 1]))
            idx += sz
    return bounds

def compute_dates_global(n_acts: int, start_str: str, end_str: str) -> List[Dict[str, Any]]:
    try:
        start_dt = datetime.fromisoformat(start_str)
        end_dt = datetime.fromisoformat(end_str)
    except Exception:
        return [{"Ч": "", "М": "", "Г": "", "Чнач": "", "Мнач": "", "Гн": "", "date_end": ""} for _ in range(n_acts)]
    days = bdays_range(start_dt, end_dt)
    spans = split_business_days(days, n_acts)
    out = []
    for s, e in spans:
        if s is None or e is None:
            out.append({"Ч": "", "М": "", "Г": "", "Чнач": "", "Мнач": "", "Гн": "", "date_end": ""})
            continue
        out.append({
            "Ч": str(e.day),
            "М": RU_MONTHS_GEN[e.month],
            "Г": str(e.year)[-1],
            "Чнач": str(s.day),
            "Мнач": RU_MONTHS_GEN[s.month],
            "Гн": str(s.year)[-1],
            "date_end": e.strftime("%Y-%m-%d")
        })
    return out

def get_month_genitive(month_num):
    """Переводит номер месяца в родительный падеж"""
    if isinstance(month_num, str):
        try:
            month_num = int(month_num)
        except (ValueError, TypeError):
            return ""
    
    return RU_MONTHS_GEN.get(month_num, "")

def render_docx(template_path: Path, context: Dict[str, Any]) -> bytes:
    try:
        if not template_path.exists():
            raise Exception(f"Шаблон не найден: {template_path}")
            
        tpl = DocxTemplate(str(template_path))
        
        # Очищаем контекст от None значений и лишних пробелов
        clean_context = {}
        for key, value in context.items():
            if value is None:
                clean_context[key] = ""
            else:
                # Убираем лишние пробелы и переносы строк
                clean_value = str(value).strip()
                clean_context[key] = clean_value
                
        tpl.render(clean_context)
        out = io.BytesIO()
        tpl.save(out)
        out.seek(0)
        return out.getvalue()
    except Exception as e:
        print(f"Error rendering DOCX: {str(e)}")
        raise Exception(f"Ошибка рендеринга шаблона: {str(e)}")

def save_and_convert_to_pdf(docx_bytes: bytes) -> bytes:
    try:
        pythoncom.CoInitialize()
        tmp_dir = Path("tmp_previews")
        tmp_dir.mkdir(exist_ok=True)
        docx_path = tmp_dir / "preview.docx"
        pdf_path = tmp_dir / "preview.pdf"
        
        # Очищаем старые файлы
        if docx_path.exists():
            docx_path.unlink()
        if pdf_path.exists():
            pdf_path.unlink()
            
        with open(docx_path, "wb") as f:
            f.write(docx_bytes)
            
        # Проверяем что файл создался
        if not docx_path.exists():
            raise Exception("Не удалось создать временный DOCX файл")
            
        docx2pdf_convert(str(docx_path), str(pdf_path))
        
        # Проверяем что PDF создался
        if not pdf_path.exists():
            raise Exception("Не удалось конвертировать в PDF. Убедитесь что установлен Microsoft Word")
            
        with open(pdf_path, "rb") as f:
            pdf_bytes = f.read()
            
        # Очищаем временные файлы
        if docx_path.exists():
            docx_path.unlink()
        if pdf_path.exists():
            pdf_path.unlink()
            
        return pdf_bytes
    except Exception as e:
        print(f"Error converting to PDF: {str(e)}")
        raise Exception(f"Ошибка конвертации в PDF: {str(e)}")
    finally:
        pythoncom.CoUninitialize()

# --- Load templates ---
def load_templates():
    templates = {}
    tpl_dir = "templates"
    os.makedirs(tpl_dir, exist_ok=True)
    for fname in os.listdir(tpl_dir):
        if fname.endswith(".docx"):
            templates[fname] = os.path.join(tpl_dir, fname)
    if not templates:
        templates["No templates"] = None
    return templates

# --- Load sessions ---
def load_sessions():
    sessions = []
    sess_dir = "sessions"
    os.makedirs(sess_dir, exist_ok=True)
    for fname in os.listdir(sess_dir):
        if fname.endswith(".json"):
            sessions.append(fname)
    return sessions

# --- Load SP regulations ---
def load_sp_regulations():
    sp_file = Path("sp_regulations.json")
    if sp_file.exists():
        try:
            with open(sp_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                print(f"Loaded sp_regulations: {data}")
                return data
        except json.JSONDecodeError as e:
            print(f"Error decoding sp_regulations.json: {e}")
            return {}
    print("sp_regulations.json not found")
    return {}

# --- HTML template with improved design ---
INDEX_HTML = """
<!doctype html>
<html>
<head>
    <meta charset="utf-8">
    <title>Генератор АОСР</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --primary: #2563eb;
            --primary-hover: #1d4ed8;
            --secondary: #64748b;
            --success: #10b981;
            --danger: #ef4444;
            --warning: #f59e0b;
            --light: #f8fafc;
            --dark: #1e293b;
            --border: #e2e8f0;
            --shadow: 0 1px 3px rgba(0,0,0,0.1);
            --shadow-lg: 0 10px 25px rgba(0,0,0,0.1);
        }
        
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
            color: var(--dark);
        }
        
        .container {
            max-width: 1400px;
            margin: 0 auto;
            background: white;
            border-radius: 16px;
            box-shadow: var(--shadow-lg);
            overflow: hidden;
        }
        
        .header {
            background: linear-gradient(135deg, var(--primary), var(--primary-hover));
            color: white;
            padding: 30px 40px;
            text-align: center;
        }
        
        .header h1 {
            font-size: 2.5rem;
            font-weight: 700;
            margin-bottom: 10px;
        }
        
        .header p {
            font-size: 1.1rem;
            opacity: 0.9;
        }
        
        .content {
            padding: 40px;
        }
        
        .section {
            background: var(--light);
            border-radius: 12px;
            padding: 30px;
            margin-bottom: 30px;
            border: 1px solid var(--border);
        }
        
        .section h2 {
            font-size: 1.5rem;
            font-weight: 600;
            color: var(--primary);
            margin-bottom: 20px;
            padding-bottom: 15px;
            border-bottom: 2px solid var(--primary);
        }
        
        .card {
            background: white;
            border-radius: 8px;
            padding: 25px;
            margin-bottom: 20px;
            border: 1px solid var(--border);
            box-shadow: var(--shadow);
        }
        
        .form-group {
            margin-bottom: 20px;
        }
        
        label {
            display: block;
            font-weight: 500;
            margin-bottom: 8px;
            color: var(--dark);
        }
        
        input[type="text"],
        input[type="date"],
        textarea,
        select {
            width: 100%;
            padding: 12px 16px;
            border: 2px solid var(--border);
            border-radius: 8px;
            font-size: 14px;
            transition: all 0.3s ease;
        }
        
        input[type="text"]:focus,
        input[type="date"]:focus,
        textarea:focus,
        select:focus {
            outline: none;
            border-color: var(--primary);
            box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.1);
        }
        
        textarea {
            min-height: 80px;
            resize: vertical;
        }
        
        .btn {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            padding: 12px 24px;
            border: none;
            border-radius: 8px;
            font-size: 14px;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.3s ease;
            text-decoration: none;
            gap: 8px;
        }
        
        .btn-primary {
            background: var(--primary);
            color: white;
        }
        
        .btn-primary:hover {
            background: var(--primary-hover);
            transform: translateY(-1px);
        }
        
        .btn-secondary {
            background: var(--secondary);
            color: white;
        }
        
        .btn-success {
            background: var(--success);
            color: white;
        }
        
        .btn-danger {
            background: var(--danger);
            color: white;
        }
        
        .btn-warning {
            background: var(--warning);
            color: white;
        }
        
        .btn:hover {
            transform: translateY(-1px);
            box-shadow: var(--shadow);
        }
        
        .btn-sm {
            padding: 8px 16px;
            font-size: 13px;
        }
        
        .btn-group {
            display: flex;
            gap: 12px;
            flex-wrap: wrap;
        }
        
        .hot-container-wrapper {
            background: white;
            border-radius: 8px;
            border: 1px solid var(--border);
            margin: 20px 0;
            overflow: hidden;
            position: relative;
        }
        
        #hot-container {
            height: 400px;
            overflow: hidden;
        }
        
        .fullscreen {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: white;
            z-index: 1000;
        }
        
        .template-list {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 15px;
            margin-top: 15px;
        }
        
        .template-item {
            background: white;
            padding: 15px;
            border-radius: 8px;
            border: 1px solid var(--border);
            font-size: 14px;
        }
        
        .alert {
            padding: 16px;
            border-radius: 8px;
            margin: 20px 0;
            border-left: 4px solid;
        }
        
        .alert-success {
            background: #f0fdf4;
            border-color: var(--success);
            color: #166534;
        }
        
        .alert-error {
            background: #fef2f2;
            border-color: var(--danger);
            color: #dc2626;
        }
        
        .alert-warning {
            background: #fffbeb;
            border-color: var(--warning);
            color: #d97706;
        }
        
        .preview-container {
            margin-top: 30px;
            border: 2px solid var(--border);
            border-radius: 12px;
            overflow: hidden;
        }
        
        .preview-header {
            background: var(--primary);
            color: white;
            padding: 15px 20px;
            font-weight: 500;
        }
        
        .preview-content {
            padding: 20px;
        }
        
        .session-management {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
        }
        
        .add-row-btn {
            position: absolute;
            bottom: 10px;
            right: 10px;
            z-index: 100;
            width: 40px;
            height: 40px;
            border-radius: 50%;
            background: var(--success);
            color: white;
            border: none;
            font-size: 20px;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            box-shadow: var(--shadow);
        }
        
        .add-row-btn:hover {
            transform: scale(1.1);
            background: #0da271;
        }
        
        /* Стили для спойлера */
        .spoiler {
            border: 1px solid var(--border);
            border-radius: 8px;
            margin-bottom: 20px;
            overflow: hidden;
        }
        
        .spoiler-header {
            background: var(--light);
            padding: 15px 20px;
            cursor: pointer;
            user-select: none;
            display: flex;
            align-items: center;
            justify-content: space-between;
            transition: background-color 0.3s ease;
        }
        
        .spoiler-header:hover {
            background: #e2e8f0;
        }
        
        .spoiler-title {
            font-weight: 600;
            color: var(--primary);
            font-size: 1.1rem;
        }
        
        .spoiler-arrow {
            transition: transform 0.3s ease;
            font-size: 1.2rem;
            color: var(--primary);
        }
        
        .spoiler-content {
            padding: 0;
            max-height: 0;
            overflow: hidden;
            transition: max-height 0.3s ease, padding 0.3s ease;
        }
        
        .spoiler.open .spoiler-arrow {
            transform: rotate(180deg);
        }
        
        .spoiler.open .spoiler-content {
            max-height: 2000px;
            padding: 20px;
        }
        
        @media (max-width: 768px) {
            .content {
                padding: 20px;
            }
            
            .session-management {
                grid-template-columns: 1fr;
            }
            
            .btn-group {
                flex-direction: column;
            }
        }
    </style>
    <script src="https://cdn.jsdelivr.net/npm/handsontable/dist/handsontable.full.min.js"></script>
    <link href="https://cdn.jsdelivr.net/npm/handsontable/dist/handsontable.full.min.css" rel="stylesheet" media="screen">
    <script>
        let rowCount = {{ rows_data|length }};
        let hot;

        // Ensure we have valid data
        function ensureValidData(rows) {
            if (!Array.isArray(rows) || rows.length === 0) {
                return [{
                    "шаблон": "", "номер": "", "Наименование_работ": "",
                    "Начало": "", "Конец": "",
                    "Материалы_и_серты": "", "Схемы_и_тд": "",
                    "Примечание": ""
                }];
            }
            return rows;
        }

        function initHot() {
            const container = document.getElementById('hot-container');
            let data = {{ rows_data|tojson|safe }};
            
            // Ensure data is properly formatted
            data = ensureValidData(data);
            
            console.log('Initializing Handsontable with data:', data);
            
            // Destroy existing instance if it exists
            if (hot) {
                hot.destroy();
            }
            
            hot = new Handsontable(container, {
                data: data,
                rowHeaders: true,
                colHeaders: ['✓', 'Шаблон', 'Номер', 'Наименование работ', 'Начало', 'Конец', 'Материалы и серты', 'Схемы и тд', 'Разрешает пр-во работ по', 'СП'],
                columns: [
                    {
                        data: 'selected',
                        type: 'checkbox',
                        width: 30
                    },
                    {
                        data: 'шаблон',
                        type: 'dropdown',
                        source: {{ templates.keys()|list|tojson|safe }},
                        width: 120
                    },
                    {
                        data: 'номер',
                        type: 'text',
                        width: 80
                    },
                    {
                        data: 'Наименование_работ',
                        type: 'text',
                        width: 200
                    },
                    {
                        data: 'Начало',
                        type: 'date',
                        dateFormat: 'DD.MM.YYYY',
                        correctFormat: true,
                        defaultDate: null,
                        datePickerConfig: {
                            showOn: 'focus',
                            dateFormat: 'd.m.Y',
                            locale: 'ru'
                        }
                    },
                    {
                        data: 'Конец',
                        type: 'date',
                        dateFormat: 'DD.MM.YYYY',
                        correctFormat: true,
                        defaultDate: null,
                        datePickerConfig: {
                            showOn: 'focus',
                            dateFormat: 'd.m.Y',
                            locale: 'ru'
                        }
                    },
                    {
                        data: 'Материалы_и_серты',
                        type: 'text',
                        width: 150
                    },
                    {
                        data: 'Схемы_и_тд',
                        type: 'text',
                        width: 150
                    },
                    {
                        data: 'Разрешает_пр_во_работ_по',
                        type: 'text',
                        width: 180
                    },
                    {
                        data: 'СП',
                        type: 'autocomplete',
                        source: {{ sp_regulations.values()|list|tojson|safe }},
                        multiple: true,
                        trimDropdown: false
                    }
                ],
                contextMenu: true,
                filters: true,
                manualColumnResize: true,
                manualRowResize: true,
                copyPaste: true,
                fillHandle: true,
                licenseKey: 'non-commercial-and-evaluation',
                height: 400,
                width: '100%',
                afterChange: function(changes, source) {
                    if (source !== 'loadData') {
                        console.log('Table data changed:', changes);
                    }
                }
            });

            document.getElementById('toggle-fullscreen').addEventListener('click', function() {
                container.classList.toggle('fullscreen');
                hot.render();
            });
            
            // Обработчик для кнопки предпросмотра
            document.getElementById('preview-btn').addEventListener('click', function() {
                const previewMode = document.querySelector('input[name="preview_mode"]:checked').value;
                if (previewMode === 'single') {
                    const actNumber = document.querySelector('input[name="act_number"]').value;
                    if (!actNumber) {
                        alert('Введите номер акта для предпросмотра');
                        return;
                    }
                    
                    // Сохраняем данные таблицы
                    saveTableData();
                    
                    // Создаем FormData с данными формы
                    const form = document.getElementById('main-form');
                    const formData = new FormData(form);
                    formData.set('action', 'preview');
                    formData.set('act_number', actNumber);
                    
                    // Отправляем AJAX запрос
                    fetch('/process', {
                        method: 'POST',
                        headers: {
                            'X-Requested-With': 'XMLHttpRequest',
                            'Accept': 'application/json'
                        },
                        body: formData
                    })
                    .then(response => {
                        if (!response.headers.get('content-type')?.includes('application/json')) {
                            throw new Error('Server returned non-JSON response');
                        }
                        return response.json();
                    })
                    .then(data => {
                        if (data.success) {
                            // Открываем PDF в новом окне
                            window.open(data.preview_url, '_blank');
                        } else {
                            alert('Ошибка: ' + (data.error || 'Неизвестная ошибка'));
                        }
                    })
                    .catch(error => {
                        console.error('Error:', error);
                        alert('Ошибка при создании предпросмотра');
                    });
                } else if (previewMode === 'selected') {
                    // Получаем отмеченные строки
                    const tableData = hot.getSourceData();
                    const selectedData = tableData.filter(row => row && row.selected === true);
                    
                    if (selectedData.length === 0) {
                        alert('Отметьте строки галочками для предпросмотра');
                        return;
                    }
                    
                    // Сохраняем данные таблицы
                    saveTableData();
                    
                    // Создаем FormData с данными формы
                    const form = document.getElementById('main-form');
                    const formData = new FormData(form);
                    formData.set('action', 'preview_selected');
                    formData.set('selected_data', JSON.stringify(selectedData));
                    
                    // Отправляем AJAX запрос
                    fetch('/process', {
                        method: 'POST',
                        headers: {
                            'X-Requested-With': 'XMLHttpRequest',
                            'Accept': 'application/json'
                        },
                        body: formData
                    })
                    .then(response => {
                        if (!response.headers.get('content-type')?.includes('application/json')) {
                            throw new Error('Server returned non-JSON response');
                        }
                        return response.json();
                    })
                    .then(data => {
                        if (data.success) {
                            // Открываем PDF в новом окне
                            window.open(data.preview_url, '_blank');
                        } else {
                            alert('Ошибка: ' + (data.error || 'Неизвестная ошибка'));
                        }
                    })
                    .catch(error => {
                        console.error('Error:', error);
                        alert('Ошибка при создании предпросмотра');
                    });
                }
            });
        }

        window.onload = function() {
            initHot();
            initSpoilers();
        };

        function addRow() {
            rowCount++;
            hot.alter('insert_row_below', hot.countRows() - 1);
            document.getElementById('rows').value = hot.countRows();
            hot.render();
        }

        function getTableData() {
            const data = hot.getSourceData();
            console.log('Raw table data:', data);
            return JSON.stringify(data);
        }

        function prepareFormData(action) {
            const tableData = getTableData();
            console.log('Preparing form data:', tableData);
            document.getElementById('table_data').value = tableData;
            
            // Удаляем старые скрытые поля action если есть
            const existingActions = document.querySelectorAll('input[name="action"]');
            existingActions.forEach(input => input.remove());
            
            // Создаем новое скрытое поле для действия
            const actionInput = document.createElement('input');
            actionInput.type = 'hidden';
            actionInput.name = 'action';
            actionInput.value = action;
            document.querySelector('#mainForm').appendChild(actionInput);
            
            return true;
        }

        function saveTableData() {
            if (hot) {
                const tableData = hot.getSourceData();
                console.log('Saving table data:', tableData);
                document.getElementById('table_data').value = JSON.stringify(tableData);
            }
            return true;
        }
        
        function submitForm(action) {
            console.log('submitForm called with action:', action);
            if (prepareFormData(action)) {
                console.log('Form data prepared, submitting...');
                document.querySelector('#mainForm').submit();
            }
        }
        
        function calculateDates() {
            const startDate = document.getElementById('start_date').value;
            const endDate = document.getElementById('end_date').value;
            
            if (!startDate || !endDate) {
                alert('Пожалуйста, укажите дату начала и окончания работ');
                return;
            }
            
            // Получаем текущие данные таблицы
            const currentData = hot.getSourceData();
            const activeRows = currentData.filter(row => row && (row.шаблон || row.номер || row.Наименование_работ));
            
            if (activeRows.length === 0) {
                alert('Нет активных строк в таблице для расчета дат');
                return;
            }
            
            // AJAX запрос для расчета дат
            fetch('/calculate_dates', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-Requested-With': 'XMLHttpRequest'
                },
                body: JSON.stringify({
                    start_date: startDate,
                    end_date: endDate,
                    rows: activeRows.length
                })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success && data.dates) {
                    // Обновляем только поля дат для активных строк, сохраняя остальные данные
                    const updatedData = hot.getSourceData();
                    let dateIndex = 0;
                    
                    for (let i = 0; i < updatedData.length; i++) {
                        const row = updatedData[i];
                        // Проверяем, есть ли данные в строке
                        if (row && (row.шаблон || row.номер || row.Наименование_работ)) {
                            if (dateIndex < data.dates.length) {
                                const dateBlock = data.dates[dateIndex];
                                // Обновляем только поля дат, сохраняя остальные данные
                                if (dateBlock.start_date) {
                                    row.Начало = formatDateToDDMMYYYY(dateBlock.start_date);
                                }
                                if (dateBlock.end_date) {
                                    row.Конец = formatDateToDDMMYYYY(dateBlock.end_date);
                                }
                                dateIndex++;
                            }
                        }
                    }
                    
                    // Обновляем таблицу с сохранением всех данных
                    hot.loadData(updatedData);
                    alert('Даты успешно рассчитаны и заполнены в таблице');
                } else {
                    alert('Ошибка: ' + (data.error || 'Неизвестная ошибка'));
                }
            })
            .catch(error => {
                console.error('Error:', error);
                alert('Ошибка при расчете дат');
            });
        }
        
        function formatDateToDDMMYYYY(dateStr) {
            if (!dateStr) return '';
            const date = new Date(dateStr);
            if (isNaN(date.getTime())) return dateStr; // Возвращаем как есть, если не удалось распарсить
            
            const day = String(date.getDate()).padStart(2, '0');
            const month = String(date.getMonth() + 1).padStart(2, '0');
            const year = date.getFullYear();
            
            return `${day}.${month}.${year}`;
        }
        
        function initSpoilers() {
            const spoilers = document.querySelectorAll('.spoiler-header');
            spoilers.forEach(spoiler => {
                spoiler.addEventListener('click', function() {
                    const spoilerContainer = this.parentElement;
                    spoilerContainer.classList.toggle('open');
                });
            });
        }
        
        // Обработчик для переключения режима предпросмотра
        document.querySelectorAll('input[name="preview_mode"]').forEach(input => {
            input.addEventListener('change', function() {
                const previewMode = this.value;
                if (previewMode === 'single') {
                    document.getElementById('single-preview-mode').style.display = 'block';
                    document.getElementById('preview-selected-btn').style.display = 'none';
                } else if (previewMode === 'selected') {
                    document.getElementById('single-preview-mode').style.display = 'none';
                    document.getElementById('preview-selected-btn').style.display = 'block';
                }
            });
        });
    </script>
</head>
<body>
<div class="container">
    <div class="header">
        <h1>Генератор АОСР</h1>
        <p>Автоматическое формирование актов освидетельствования скрытых работ</p>
    </div>

    <div class="content">
        <!-- Upload Templates Section -->
        <div class="section">
            <h2>📁 Загрузка шаблонов</h2>
            <form method="post" action="/upload_template" enctype="multipart/form-data" class="card">
                <div class="form-group">
                    <label>Выберите файлы шаблонов (.docx):</label>
                    <input type="file" name="template" accept=".docx" multiple style="padding: 10px; border: 2px dashed var(--border);">
                </div>
                <button type="submit" class="btn btn-primary">
                    📤 Загрузить шаблоны
                </button>
            </form>

            {% if templates %}
            <div class="template-list">
                {% for template in templates.keys() %}
                <div class="template-item">
                    📄 {{ template }}
                </div>
                {% endfor %}
            </div>
            {% else %}
            <div class="alert alert-warning">
                ⚠️ Шаблоны не загружены
            </div>
            {% endif %}
        </div>

        <!-- Main Form Section -->
        <div class="section">
            <h2>📋 Основные настройки</h2>
            
            <form id="main-form" method="post" action="/process" onsubmit="return saveTableData()">
                <!-- Постоянные данные в спойлере -->
                <div class="spoiler">
                    <div class="spoiler-header">
                        <span class="spoiler-title">📝 Постоянные данные</span>
                        <span class="spoiler-arrow">▼</span>
                    </div>
                    <div class="spoiler-content">
                        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 20px;">
                            <div class="form-group">
                                <label>Объект:</label>
                                <textarea name="Объект">{{ constant_fields.get('Объект', '') }}</textarea>
                            </div>
                            <div class="form-group">
                                <label>Застройщик:</label>
                                <textarea name="Застройщик">{{ constant_fields.get('Застройщик', '') }}</textarea>
                            </div>
                            <div class="form-group">
                                <label>Строитель:</label>
                                <textarea name="Строитель">{{ constant_fields.get('Строитель', '') }}</textarea>
                            </div>
                            <div class="form-group">
                                <label>Проектная организация:</label>
                                <textarea name="Проектная_организация">{{ constant_fields.get('Проектная_организация', '') }}</textarea>
                            </div>
                            <div class="form-group">
                                <label>Проект или ТЗ:</label>
                                <textarea name="Проект_или_ТЗ">{{ constant_fields.get('Проект_или_ТЗ', '') }}</textarea>
                            </div>
                            <div class="form-group">
                                <label>Должность представителя застройщика:</label>
                                <textarea name="Представитель_застр">{{ constant_fields.get('Представитель_застр', '') }}</textarea>
                            </div>
                            <div class="form-group">
                                <label>ФИО застройщика:</label>
                                <textarea name="ФИО_застр">{{ constant_fields.get('ФИО_застр', '') }}</textarea>
                            </div>
                            <div class="form-group">
                                <label>Распоряжение на застройщика:</label>
                                <textarea name="Распор_застр">{{ constant_fields.get('Распор_застр', '') }}</textarea>
                            </div>
                            <div class="form-group">
                                <label>Должность производителя работ:</label>
                                <textarea name="Пр_раб">{{ constant_fields.get('Пр_раб', '') }}</textarea>
                            </div>
                            <div class="form-group">
                                <label>ФИО производителя работ:</label>
                                <textarea name="ФИО_Пр_раб">{{ constant_fields.get('ФИО_Пр_раб', '') }}</textarea>
                            </div>
                            <div class="form-group">
                                <label>Распоряжение на производителя работ:</label>
                                <textarea name="Распор_пр_раб">{{ constant_fields.get('Распор_пр_раб', '') }}</textarea>
                            </div>
                            <div class="form-group">
                                <label>Должность стройконтроля:</label>
                                <textarea name="Строй_контроль_Должность">{{ constant_fields.get('Строй_контроль_Должность', '') }}</textarea>
                            </div>
                            <div class="form-group">
                                <label>ФИО стройконтроля:</label>
                                <textarea name="ФИО_Стройк">{{ constant_fields.get('ФИО_Стройк', '') }}</textarea>
                            </div>
                            <div class="form-group">
                                <label>Распоряжение на стройконтроль:</label>
                                <textarea name="Распор_стройк">{{ constant_fields.get('Распор_стройк', '') }}</textarea>
                            </div>
                            <div class="form-group">
                                <label>Должность проектировщика:</label>
                                <textarea name="Проектировщик_должность">{{ constant_fields.get('Проектировщик_должность', '') }}</textarea>
                            </div>
                            <div class="form-group">
                                <label>ФИО проектировщика:</label>
                                <textarea name="Проектировщик_ФИО">{{ constant_fields.get('Проектировщик_ФИО', '') }}</textarea>
                            </div>
                            <div class="form-group">
                                <label>Распоряжение проектировщика:</label>
                                <textarea name="Распоряжение_проект">{{ constant_fields.get('Распоряжение_проект', '') }}</textarea>
                            </div>
                            <div class="form-group">
                                <label>Выполнил работы:</label>
                                <textarea name="Выполнил_работы">{{ constant_fields.get('Выполнил_работы', '') }}</textarea>
                            </div>
                            <div class="form-group">
                                <label>Иные должность:</label>
                                <textarea name="Иные_долж">{{ constant_fields.get('Иные_долж', '') }}</textarea>
                            </div>
                            <div class="form-group">
                                <label>ФИО иные:</label>
                                <textarea name="ФИО_Иные">{{ constant_fields.get('ФИО_Иные', '') }}</textarea>
                            </div>
                            <div class="form-group">
                                <label>Распоряжение иные:</label>
                                <textarea name="Распор_иные">{{ constant_fields.get('Распор_иные', '') }}</textarea>
                            </div>
                            <div class="form-group">
                                <label>Организация субподрядчик:</label>
                                <textarea name="Организация_исполнитель">{{ constant_fields.get('Организация_исполнитель', '') }}</textarea>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Dates and Copies -->
                <div class="card">
                    <h3 style="margin-bottom: 20px; color: var(--primary);">Даты и параметры</h3>
                    <div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 20px;">
                        <div class="form-group">
                            <label>Дата начала работ:</label>
                            <input type="date" name="start_date" id="start_date" value="{{ start_date }}">
                        </div>
                        <div class="form-group">
                            <label>Дата окончания работ:</label>
                            <input type="date" name="end_date" id="end_date" value="{{ end_date }}">
                        </div>
                        <div class="form-group" style="display: flex; align-items: flex-end;">
                            <button type="button" onclick="calculateDates()" class="btn btn-secondary" style="width: 100%;">
                                📅 Рассчитать даты
                            </button>
                        </div>
                        <div class="form-group">
                            <label>Кол-во экземпляров:</label>
                            <select name="Экз">
                                <option value="1" {% if constant_fields.get('Экз', '2') == '1' %}selected{% endif %}>1</option>
                                <option value="2" {% if constant_fields.get('Экз', '2') == '2' %}selected{% endif %}>2</option>
                                <option value="3" {% if constant_fields.get('Экз', '2') == '3' %}selected{% endif %}>3</option>
                            </select>
                        </div>
                    </div>
                </div>

                <!-- Table Section -->
                <div class="card">
                    <h3 style="margin-bottom: 20px; color: var(--primary);">Реестр актов</h3>
                    
                    <div class="hot-container-wrapper">
                        <div id="hot-container"></div>
                        <button type="button" class="add-row-btn" onclick="addRow()" title="Добавить строку">+</button>
                    </div>
                    
                    <input type="hidden" id="rows" name="rows" value="{{ rows_data|length }}">
                    <input type="hidden" name="table_data" id="table_data" value="">
                    
                    <div class="btn-group">
                        <button type="button" onclick="addRow()" class="btn btn-success">
                            ➕ Добавить акт
                        </button>
                        <button type="button" id="toggle-fullscreen" class="btn btn-secondary">
                            📺 Полноэкранный режим
                        </button>
                        <button type="button" onclick="calculateDates()" class="btn btn-primary">
                            📆 Рассчитать даты
                        </button>
                    </div>
                </div>

                <!-- Preview Section -->
                <div class="card">
                    <h3 style="margin-bottom: 20px; color: var(--primary);">Предпросмотр актов</h3>
                    <div class="form-group">
                        <label>Выберите режим предпросмотра:</label>
                        <div style="display: flex; gap: 10px; margin-bottom: 15px;">
                            <label style="display: flex; align-items: center; gap: 5px;">
                                <input type="radio" name="preview_mode" value="single" checked>
                                По номеру акта
                            </label>
                            <label style="display: flex; align-items: center; gap: 5px;">
                                <input type="radio" name="preview_mode" value="selected">
                                Выделенные строки
                            </label>
                        </div>
                    </div>
                    <div id="single-preview-mode">
                        <div class="form-group">
                            <label>Номер акта для предпросмотра:</label>
                            <input type="text" name="act_number" value="{{ act_number or '' }}" placeholder="Введите номер акта">
                        </div>
                    </div>
                    <div class="btn-group">
                        <button type="button" id="preview-btn" class="btn btn-primary">
                            👁️ Предпросмотр
                        </button>
                        <button type="button" id="preview-selected-btn" class="btn btn-success" style="display: none;">
                            📄 Общий PDF выделенных
                        </button>
                    </div>
                </div>

                <!-- Generate Section -->
                <div class="card">
                    <h3 style="margin-bottom: 20px; color: var(--primary);">Формирование документов</h3>
                    <button type="submit" name="action" value="generate" class="btn btn-success" style="font-size: 16px; padding: 15px 30px;">
                        🎯 Сформировать архив
                    </button>
                </div>

                <!-- Session Management -->
                <div class="card">
                    <h3 style="margin-bottom: 20px; color: var(--primary);">Управление сессией</h3>
                    <div class="session-management">
                        <div>
                            <div class="form-group">
                                <label>Имя сессии:</label>
                                <input type="text" name="session_name" value="{{ session_name or '' }}" placeholder="Введите имя сессии">
                            </div>
                            <button type="submit" name="action" value="save_session" class="btn btn-primary">
                                💾 Сохранить сессию
                            </button>
                        </div>
                        
                        <div>
                            <div class="form-group">
                                <label>Загрузить сессию:</label>
                                <select name="load_session_name" class="form-control">
                                    {% for sess in sessions %}
                                        <option value="{{ sess }}">{{ sess }}</option>
                                    {% endfor %}
                                </select>
                            </div>
                            <div class="btn-group">
                                <button type="submit" name="action" value="load_session" class="btn btn-secondary">
                                    📂 Загрузить сессию
                                </button>
                                <button type="submit" name="action" value="new_session" class="btn btn-warning">
                                    🆕 Новая сессия
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            </form>

            <!-- Preview PDF -->
            {% if pdf_b64 %}
            <div class="preview-container">
                <div class="preview-header">
                    Предпросмотр акта №{{ act_number }}
                </div>
                <div class="preview-content">
                    <iframe src="data:application/pdf;base64,{{ pdf_b64 }}" width="100%" height="600px" style="border: none;"></iframe>
                    <div style="margin-top: 15px;">
                        <a href="/download_preview/{{ act_number }}" class="btn btn-primary">
                            📥 Скачать PDF
                        </a>
                    </div>
                </div>
            </div>
            {% endif %}

            <!-- Flash Messages -->
            {% with messages = get_flashed_messages() %}
                {% if messages %}
                    {% for message in messages %}
                        <div class="alert {% if 'error' in message.lower() %}alert-error{% elif 'успешно' in message.lower() %}alert-success{% else %}alert-warning{% endif %}">
                            {{ message }}
                        </div>
                    {% endfor %}
                {% endif %}
            {% endwith %}
        </div>
    </div>
</div>

<template id="row-template" style="display: none;">
    <tr>
        <td data-hot-col="0"></td>
        <td data-hot-col="1"></td>
        <td data-hot-col="2"></td>
        <td data-hot-col="3"></td>
        <td data-hot-col="4"></td>
        <td data-hot-col="5"></td>
        <td data-hot-col="6"></td>
        <td data-hot-col="7"></td>
        <td data-hot-col="8"></td>
    </tr>
</template>
</body>
</html>
"""

# --- Routes ---
@app.route("/")
def index():
    templates = load_templates()
    sessions = load_sessions()
    constant_fields = session.get('constant_fields', {})
    start_date = session.get('start_date', '')
    end_date = session.get('end_date', '')
    rows_data = session.get('rows_data', [])
    
    # Загружаем существующие данные из JSON файла
    session_id = session.get("session_id")
    session_rows = []
    session_fields = {}
    
    if session_id:
        session_file = Path("sessions") / f"{session_id}.json"
        if session_file.exists():
            try:
                with open(session_file, "r", encoding="utf-8") as f:
                    session_data = json.load(f)
                    session_rows = session_data.get("rows_data", [])
                    session_fields = session_data.get("constant_fields", {})
            except Exception as e:
                print(f"Error loading session data: {e}")
                
    # Объединяем данные из сессии и JSON файла
    rows_data = session_rows or rows_data
    constant_fields = session_fields or constant_fields
    
    # Добавляем пустую строку по умолчанию, если таблица пустая
    if not rows_data:
        rows_data = [{
            "шаблон": "", "номер": "", "Наименование_работ": "", 
            "Начало": "", "Конец": "", 
            "Материалы_и_серты": "", "Схемы_и_тд": "", 
            "Разрешает_пр_во_работ_по": "", "СП": "", "selected": False
        }]
    
    sp_regulations = load_sp_regulations()
    pdf_b64 = session.pop('pdf_b64', None)
    act_number = session.pop('act_number', None)
    return render_template_string(INDEX_HTML, templates=templates, sessions=sessions, constant_fields=constant_fields, start_date=start_date, end_date=end_date, rows_data=rows_data, pdf_b64=pdf_b64, act_number=act_number, sp_regulations=sp_regulations)

@app.route("/preview_file/<filename>")
def preview_file(filename):
    """Serves preview files via HTTP URL"""
    tmp_dir = Path("tmp_previews")
    file_path = tmp_dir / filename
    
    if file_path.exists() and file_path.suffix in [".pdf", ".docx"]:
        return send_file(file_path, as_attachment=False)
    else:
        return "File not found", 404

@app.route("/upload_template", methods=["POST"])
def upload_template():
    if "template" not in request.files:
        flash("Файл не выбран")
        return redirect(url_for("index"))
    
    file = request.files["template"]
    if file.filename == "":
        flash("Файл не выбран")
        return redirect(url_for("index"))
    
    if file and file.filename.endswith(".docx"):
        templates_dir = Path("templates")
        templates_dir.mkdir(exist_ok=True)
        file_path = templates_dir / file.filename
        file.save(str(file_path))
        flash(f"Шаблон {file.filename} загружен успешно")
    else:
        flash("Загружайте только файлы .docx")
    
    return redirect(url_for("index"))

@app.route("/process", methods=["POST"])
def process():
    try:
        templates = load_templates()
        constant_fields = {
            "Объект": request.form.get("Объект", ""),
            "Застройщик": request.form.get("Застройщик", ""),
            "Строитель": request.form.get("Строитель", ""),
            "Проектная_организация": request.form.get("Проектная_организация", ""),
            "Проект_или_ТЗ": request.form.get("Проект_или_ТЗ", ""),
            "Представитель_застр": request.form.get("Представитель_застр", ""),
            "ФИО_застр": request.form.get("ФИО_застр", ""),
            "Распор_застр": request.form.get("Распор_застр", ""),
            "Пр_раб": request.form.get("Пр_раб", ""),
            "ФИО_Пр_раб": request.form.get("ФИО_Пр_раб", ""),
            "Распор_пр_раб": request.form.get("Распор_пр_раб", ""),
            "Строй_контроль_Должность": request.form.get("Строй_контроль_Должность", ""),
            "ФИО_Стройк": request.form.get("ФИО_Стройк", ""),
            "Распор_стройк": request.form.get("Распор_стройк", ""),
            "Проектировщик_должность": request.form.get("Проектировщик_должность", ""),
            "Проектировщик_ФИО": request.form.get("Проектировщик_ФИО", ""),
            "Распоряжение_проект": request.form.get("Распоряжение_проект", ""),
            "Выполнил_работы": request.form.get("Выполнил_работы", ""),
            "Иные_долж": request.form.get("Иные_долж", ""),
            "ФИО_Иные": request.form.get("ФИО_Иные", ""),
            "Распор_иные": request.form.get("Распор_иные", ""),
            "Организация_исполнитель": request.form.get("Организация_исполнитель", ""),
            "Экз": request.form.get("Экз", "2"),
        }
        start_date = request.form.get("start_date", "")
        end_date = request.form.get("end_date", "")
        rows = int(request.form.get("rows", 0))

        # Получаем данные из Handsontable
        rows_data = request.form.get("table_data", "[]")
        try:
            rows_data = json.loads(rows_data) if rows_data else []
        except json.JSONDecodeError as e:
            print(f"JSON decode error: {e}")
            rows_data = []

        # Преобразуем данные в нужный формат
        formatted_rows_data = []
        sp_regulations = load_sp_regulations()
        
        print(f"Raw rows_data received: {rows_data}")
        
        for row in rows_data:
            if not row:  # Пропускаем пустые строки
                continue
                
            # Если это объект (словарь), работаем с ним напрямую
            if isinstance(row, dict):
                formatted_row = {
                    "шаблон": str(row.get("шаблон", "")).strip(),
                    "номер": str(row.get("номер", "")).strip(),
                    "Наименование_работ": str(row.get("Наименование_работ", "")).strip(),
                    "Начало": str(row.get("Начало", "")).strip(),
                    "Конец": str(row.get("Конец", "")).strip(),
                    "Материалы_и_серты": str(row.get("Материалы_и_серты", "")).strip(),
                    "Схемы_и_тд": str(row.get("Схемы_и_тд", "")).strip(),
                    "Разрешает_пр_во_работ_по": str(row.get("Разрешает_пр_во_работ_по", "")).strip(),
                    "СП": str(row.get("СП", "")).strip(),
                    "selected": row.get("selected", False)
                }
            else:
                # Если это массив, обрабатываем как раньше
                while len(row) < 9:
                    row.append("")
                formatted_row = {
                    "шаблон": str(row[0]).strip() if row[0] else "",
                    "номер": str(row[1]).strip() if row[1] else "",
                    "Наименование_работ": str(row[2]).strip() if row[2] else "",
                    "Начало": str(row[3]).strip() if row[3] else "",
                    "Конец": str(row[4]).strip() if row[4] else "",
                    "Материалы_и_серты": str(row[5]).strip() if row[5] else "",
                    "Схемы_и_тд": str(row[6]).strip() if row[6] else "",
                    "Разрешает_пр_во_работ_по": str(row[7]).strip() if row[7] else "",
                    "СП": str(row[8]).strip() if row[8] else "",
                    "selected": False
                }
                
            if formatted_row["СП"]:
                selected_keys = [k for k, v in sp_regulations.items() if v in formatted_row["СП"].split(", ")]
                sp_values = [sp_regulations.get(key, "") for key in selected_keys]
                formatted_row["СП"] = ", ".join(sp_values)
                
            # Добавляем только строки с заполненными данными
            if any(formatted_row.values()):
                formatted_rows_data.append(formatted_row)
                
        print(f"Formatted rows_data: {formatted_rows_data}")

        # Сохраняем только основные данные в сессию
        session['start_date'] = start_date
        session['end_date'] = end_date
        
        # Сохраняем данные в JSON файл вместо session (избегаем больших cookie)
        session_id = session.get("session_id", str(uuid.uuid4()))
        session["session_id"] = session_id
        
        session_data = {
            "rows_data": formatted_rows_data,
            "constant_fields": constant_fields
        }
        
        sessions_dir = Path("sessions")
        sessions_dir.mkdir(exist_ok=True)
        session_file = sessions_dir / f"{session_id}.json"
        
        try:
            with open(session_file, "w", encoding="utf-8") as f:
                json.dump(session_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Error saving session: {e}")

        action = request.form.get("action")

        if action == "generate":
            try:
                mem_zip = io.BytesIO()
                with zipfile.ZipFile(mem_zip, "w", zipfile.ZIP_DEFLATED) as zf:
                    for i, row in enumerate(formatted_rows_data):
                        tpl_id = row["шаблон"]
                        if not tpl_id or tpl_id not in templates or tpl_id == "No templates":
                            print(f"Skipping act {row['номер']} due to missing or invalid template: {tpl_id}")
                            continue
                        context = constant_fields.copy()
                        context.update({
                            "номер": row["номер"],
                            "Наименование_работ": row["Наименование_работ"],
                            "Начало": row["Начало"],
                            "Конец": row["Конец"],
                            "Материалы_и_серты": row["Материалы_и_серты"],
                            "Схемы_и_тд": row["Схемы_и_тд"],
                            "Разрешает_пр_во_работ_по": row["Разрешает_пр_во_работ_по"],
                            "Разрешает_пр": row["Разрешает_пр_во_работ_по"],  # Короткий вариант
                            "СП": row["СП"],
                        })
                        
                        # Используем даты из таблицы для ключей шаблона
                        if row["Начало"]:
                            try:
                                start_date_obj = datetime.strptime(row["Начало"], "%d.%m.%Y")
                                context.update({
                                    "Чнач": start_date_obj.day,
                                    "Мнач": get_month_genitive(start_date_obj.month),
                                    "Гн": start_date_obj.year
                                })
                            except ValueError:
                                print(f"Invalid start date format in row {i+1}: {row['Начало']}")
                        
                        if row["Конец"]:
                            try:
                                end_date_obj = datetime.strptime(row["Конец"], "%d.%m.%Y")
                                context.update({
                                    "Ч": end_date_obj.day,
                                    "М": get_month_genitive(end_date_obj.month),
                                    "Г": end_date_obj.year
                                })
                            except ValueError:
                                print(f"Invalid end date format in row {i+1}: {row['Конец']}")
                        
                        template_path = Path(templates[tpl_id])
                        if template_path.exists():
                            try:
                                docx_bytes = render_docx(template_path, context)
                                if docx_bytes:
                                    fname = f"АОСР_{normalize_filename(row['номер']) or str(i+1)}.docx"
                                    zf.writestr(fname, docx_bytes)
                            except Exception as e:
                                print(f"Ошибка обработки строки {i+1}: {str(e)}")
                                continue
                        else:
                            print(f"Шаблон не найден: {template_path}")
                mem_zip.seek(0)
                return send_file(mem_zip, as_attachment=True, download_name="acts.zip")
            except Exception as e:
                print(f"Error generating archive: {str(e)}")
                flash(f"Ошибка при генерации архива: {str(e)}")
                return redirect(url_for("index"))

        elif action == "preview":
            act_number = request.form.get("act_number", "")
            if not act_number:
                return jsonify({"success": False, "error": "Номер акта не указан"})
                
            # Ищем акт с указанным номером
            act_data = None
            for i, row in enumerate(formatted_rows_data):
                if row["номер"] == act_number:
                    act_data = row.copy()
                    act_data["index"] = i
                    break
                    
            if not act_data:
                return jsonify({"success": False, "error": "Акт с указанным номером не найден"})
                    
            context = constant_fields.copy()
            context.update({
                "номер": act_data["номер"],
                "Наименование_работ": act_data["Наименование_работ"],
                "Начало": act_data["Начало"],
                "Конец": act_data["Конец"],
                "Материалы_и_серты": act_data["Материалы_и_серты"],
                "Схемы_и_тд": act_data["Схемы_и_тд"],
                "Разрешает_пр_во_работ_по": act_data["Разрешает_пр_во_работ_по"],
                "Разрешает_пр": act_data["Разрешает_пр_во_работ_по"],  # Короткий вариант
                "СП": act_data["СП"],
            })
            
            # Используем даты из таблицы для ключей шаблона
            if act_data["Начало"]:
                try:
                    start_date_obj = datetime.strptime(act_data["Начало"], "%d.%m.%Y")
                    context.update({
                        "Чнач": start_date_obj.day,
                        "Мнач": get_month_genitive(start_date_obj.month),
                        "Гн": start_date_obj.year
                    })
                except ValueError:
                    print(f"Invalid start date format in row {act_data['index']+1}: {act_data['Начало']}")
            
            if act_data["Конец"]:
                try:
                    end_date_obj = datetime.strptime(act_data["Конец"], "%d.%m.%Y")
                    context.update({
                        "Ч": end_date_obj.day,
                        "М": get_month_genitive(end_date_obj.month),
                        "Г": end_date_obj.year
                    })
                except ValueError:
                    print(f"Invalid end date format in row {act_data['index']+1}: {act_data['Конец']}")
            
            print(f"Context for preview: {context}")
            template_path = Path(templates[act_data["шаблон"]])
            if template_path.exists():
                try:
                    docx_bytes = render_docx(template_path, context)
                    if docx_bytes:
                        pdf_bytes = save_and_convert_to_pdf(docx_bytes)
                        if pdf_bytes:
                            # Сохраняем PDF во временную папку
                            tmp_dir = Path("tmp_previews")
                            tmp_dir.mkdir(exist_ok=True)
                            pdf_path = tmp_dir / "preview.pdf"
                            
                            with open(pdf_path, "wb") as f:
                                f.write(pdf_bytes)
                            
                            # Возвращаем JSON с HTTP URL для предпросмотра
                            preview_url = url_for("preview_file", filename="preview.pdf", _external=True)
                            return jsonify({
                                "success": True,
                                "preview_url": preview_url
                            })
                except Exception as e:
                    print(f"Error rendering DOCX: {str(e)}")
                    return jsonify({"success": False, "error": f"Ошибка создания предпросмотра: {str(e)}"})
            else:
                return jsonify({"success": False, "error": "Файл шаблона не найден"})

        elif action == "preview_selected":
            selected_data = request.form.get("selected_data", "[]")
            try:
                selected_data = json.loads(selected_data)
                print(f"Selected data: {selected_data}")  # Debug log
            except json.JSONDecodeError as e:
                print(f"JSON decode error: {e}")
                return jsonify({"success": False, "error": f"Ошибка разбора данных: {str(e)}"})
            
            if not selected_data:
                return jsonify({"success": False, "error": "Нет выделенных строк для предпросмотра"})
            
            try:
                # Создаем временную директорию, если её нет
                tmp_dir = Path("tmp_previews")
                tmp_dir.mkdir(exist_ok=True, parents=True)
                
                # Создаем временный файл для объединенного PDF
                output_pdf = tmp_dir / "combined_preview.pdf"
                
                # Инициализируем объект для объединения PDF
                merger = PdfWriter()
                
                for i, row in enumerate(selected_data):
                    try:
                        print(f"Processing row {i+1}: {row}")  # Debug log
                        
                        # Получаем ID шаблона
                        tpl_id = row.get("шаблон", "")
                        if not tpl_id or tpl_id not in templates or tpl_id == "No templates":
                            print(f"Skipping act {row.get('номер', 'N/A')} - invalid template: {tpl_id}")
                            continue
                            
                        # Создаем контекст для шаблона
                        context = constant_fields.copy()
                        context.update({
                            "номер": row.get("номер", ""),
                            "Наименование_работ": row.get("Наименование_работ", ""),
                            "Начало": row.get("Начало", ""),
                            "Конец": row.get("Конец", ""),
                            "Материалы_и_серты": row.get("Материалы_и_серты", ""),
                            "Схемы_и_тд": row.get("Схемы_и_тд", ""),
                            "Разрешает_пр_во_работ_по": row.get("Разрешает_пр_во_работ_по", ""),
                            "Разрешает_пр": row.get("Разрешает_пр_во_работ_по", ""),
                            "СП": row.get("СП", ""),
                        })
                        
                        # Обрабатываем даты
                        if row.get("Начало"):
                            try:
                                start_date_obj = datetime.strptime(row["Начало"], "%d.%m.%Y")
                                context.update({
                                    "Чнач": start_date_obj.day,
                                    "Мнач": get_month_genitive(start_date_obj.month),
                                    "Гн": start_date_obj.year
                                })
                            except ValueError as e:
                                print(f"Invalid start date format: {row.get('Начало')} - {str(e)}")
                        
                        if row.get("Конец"):
                            try:
                                end_date_obj = datetime.strptime(row["Конец"], "%d.%m.%Y")
                                context.update({
                                    "Ч": end_date_obj.day,
                                    "М": get_month_genitive(end_date_obj.month),
                                    "Г": end_date_obj.year
                                })
                            except ValueError as e:
                                print(f"Invalid end date format: {row.get('Конец')} - {str(e)}")
                        
                        # Рендерим DOCX
                        template_path = Path(templates[tpl_id])
                        if not template_path.exists():
                            print(f"Template not found: {template_path}")
                            continue
                            
                        print(f"Rendering template: {template_path}")
                        docx_bytes = render_docx(template_path, context)
                        if not docx_bytes:
                            print(f"Failed to render template: {template_path}")
                            continue
                            
                        # Конвертируем в PDF
                        print(f"Converting to PDF: {row.get('номер', 'N/A')}")
                        pdf_bytes = save_and_convert_to_pdf(docx_bytes)
                        if not pdf_bytes:
                            print(f"Failed to convert to PDF: {row.get('номер', 'N/A')}")
                            continue
                            
                        # Добавляем PDF в объединитель
                        print(f"Adding PDF to merger: {len(pdf_bytes)} bytes")
                        merger.append(io.BytesIO(pdf_bytes))
                        
                    except Exception as e:
                        print(f"Error processing row {i+1}: {str(e)}")
                        import traceback
                        traceback.print_exc()
                        continue
                
                # Если не удалось создать ни одного PDF
                if not merger.pages:
                    return jsonify({"success": False, "error": "Не удалось создать ни одного PDF файла"})
                
                # Сохраняем объединенный PDF
                print(f"Saving combined PDF to: {output_pdf}")
                with open(output_pdf, "wb") as f:
                    merger.write(f)
                
                # Проверяем, что файл создан
                if not output_pdf.exists() or output_pdf.stat().st_size == 0:
                    return jsonify({"success": False, "error": "Ошибка при создании объединенного PDF"})
                
                # Возвращаем URL для предпросмотра
                preview_url = url_for("preview_file", filename=output_pdf.name, _external=True)
                print(f"Preview URL: {preview_url}")
                
                return jsonify({
                    "success": True,
                    "preview_url": preview_url,
                    "count": len(merger.pages)
                })
                
            except Exception as e:
                print(f"Error in preview_selected: {str(e)}")
                import traceback
                traceback.print_exc()
                return jsonify({"success": False, "error": f"Внутренняя ошибка сервера: {str(e)}"})
                
            except Exception as e:
                print(f"Error generating combined PDF: {str(e)}")
                return jsonify({"success": False, "error": f"Ошибка создания общего PDF: {str(e)}"})

        elif action == "save_session":
            session_name = request.form.get("session_name", "").strip()
            if not session_name:
                flash("Введите имя сессии")
                return redirect(url_for("index"))
                
            # Get all constant fields from the form
            constant_fields = {
                'Объект': request.form.get('Объект', ''),
                'Застройщик': request.form.get('Застройщик', ''),
                'Строитель': request.form.get('Строитель', ''),
                'Проектная_организация': request.form.get('Проектная_организация', ''),
                'Проект_или_ТЗ': request.form.get('Проект_или_ТЗ', ''),
                'Представитель_застр': request.form.get('Представитель_застр', ''),
                'ФИО_застр': request.form.get('ФИО_застр', ''),
                'Распор_застр': request.form.get('Распор_застр', ''),
                'Пр_раб': request.form.get('Пр_раб', ''),
                'ФИО_Пр_раб': request.form.get('ФИО_Пр_раб', ''),
                'Распор_пр_раб': request.form.get('Распор_пр_раб', ''),
                'Строй_контроль_Должность': request.form.get('Строй_контроль_Должность', ''),
                'ФИО_Стройк': request.form.get('ФИО_Стройк', ''),
                'Распор_стройк': request.form.get('Распор_стройк', ''),
                'Проектировщик_должность': request.form.get('Проектировщик_должность', ''),
                'Проектировщик_ФИО': request.form.get('Проектировщик_ФИО', ''),
                'Распоряжение_проект': request.form.get('Распоряжение_проект', ''),
                'Выполнил_работы': request.form.get('Выполнил_работы', ''),
                'Иные_долж': request.form.get('Иные_долж', ''),
                'ФИО_Иные': request.form.get('ФИО_Иные', ''),
                'Распор_иные': request.form.get('Распор_иные', ''),
                'Организация_исполнитель': request.form.get('Организация_исполнитель', ''),
                'Экз': request.form.get('Экз', '2')
            }
            
            # Get table data from the form
            rows_data = request.form.get("table_data", "[]")
            try:
                rows_data = json.loads(rows_data) if rows_data else []
            except json.JSONDecodeError as e:
                print(f"JSON decode error: {e}")
                rows_data = []
                
            # Format the rows data
            formatted_rows_data = []
            for row in rows_data:
                if not row:
                    continue
                    
                if isinstance(row, dict):
                    formatted_row = {
                        "шаблон": str(row.get("шаблон", "")).strip(),
                        "номер": str(row.get("номер", "")).strip(),
                        "Наименование_работ": str(row.get("Наименование_работ", "")).strip(),
                        "Начало": str(row.get("Начало", "")).strip(),
                        "Конец": str(row.get("Конец", "")).strip(),
                        "Материалы_и_серты": str(row.get("Материалы_и_серты", "")).strip(),
                        "Схемы_и_тд": str(row.get("Схемы_и_тд", "")).strip(),
                        "Разрешает_пр_во_работ_по": str(row.get("Разрешает_пр_во_работ_по", "")).strip(),
                        "СП": str(row.get("СП", "")).strip(),
                        "selected": row.get("selected", False)
                    }
                else:
                    while len(row) < 9:
                        row.append("")
                    formatted_row = {
                        "шаблон": str(row[0]).strip() if row[0] else "",
                        "номер": str(row[1]).strip() if row[1] else "",
                        "Наименование_работ": str(row[2]).strip() if row[2] else "",
                        "Начало": str(row[3]).strip() if row[3] else "",
                        "Конец": str(row[4]).strip() if row[4] else "",
                        "Материалы_и_серты": str(row[5]).strip() if row[5] else "",
                        "Схемы_и_тд": str(row[6]).strip() if row[6] else "",
                        "Разрешает_пр_во_работ_по": str(row[7]).strip() if row[7] else "",
                        "СП": str(row[8]).strip() if row[8] else "",
                        "selected": False
                    }
                
                if any(formatted_row.values()):
                    formatted_rows_data.append(formatted_row)
            
            # Save to session
            session['constant_fields'] = constant_fields
            session['rows_data'] = formatted_rows_data
            
            # Create session directory if it doesn't exist
            sessions_dir = Path("sessions")
            sessions_dir.mkdir(exist_ok=True)
            
            # Generate unique session ID if it doesn't exist
            session_id = session.get("session_id", str(uuid.uuid4()))
            session["session_id"] = session_id
            
            # Prepare session data
            session_data = {
                "rows_data": formatted_rows_data,
                "constant_fields": constant_fields,
                "start_date": request.form.get("start_date", ""),
                "end_date": request.form.get("end_date", "")
            }
            
            # Save with timestamp in the filename
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            session_name = f"{session_name}_{timestamp}.json"
            session_file = sessions_dir / session_name
            
            try:
                with open(session_file, "w", encoding="utf-8") as f:
                    json.dump(session_data, f, ensure_ascii=False, indent=2)
                
                flash(f"Сессия '{session_name}' успешно сохранена")
                return redirect(url_for("index"))
                
            except Exception as e:
                print(f"Error saving session: {e}")
                flash(f"Ошибка при сохранении сессии: {str(e)}")
                return redirect(url_for("index"))

        elif action == "load_session":
            load_session_name = request.form.get("load_session_name", "").strip()
            if not load_session_name:
                flash("Выберите сессию для загрузки")
                return redirect(url_for("index"))
            
            # Ensure the sessions directory exists
            sess_dir = "sessions"
            os.makedirs(sess_dir, exist_ok=True)
            
            # Find the exact session file matching the selected name
            session_files = [f for f in os.listdir(sess_dir) if f.endswith('.json')]
            selected_file = None
            
            # First try exact match
            if load_session_name in session_files:
                selected_file = load_session_name
            else:
                # If no exact match, try to find a matching file (in case of display name vs filename mismatch)
                matching_files = [f for f in session_files if load_session_name in f]
                if matching_files:
                    selected_file = matching_files[0]
            
            if not selected_file or not os.path.exists(os.path.join(sess_dir, selected_file)):
                flash(f"Сессия '{load_session_name}' не найдена")
                return redirect(url_for("index"))
            
            try:
                sess_file = os.path.join(sess_dir, selected_file)
                with open(sess_file, 'r', encoding='utf-8') as f:
                    sess_data = json.load(f)
                
                # Clear existing session data first
                session.clear()
                
                # Get the saved rows data
                saved_rows = sess_data.get('rows_data', [])
                
                # Ensure we have at least one row
                if not saved_rows:
                    saved_rows = [{
                        "шаблон": "", "номер": "", "Наименование_работ": "",
                        "Начало": "", "Конец": "",
                        "Материалы_и_серты": "", "Схемы_и_тд": "",
                        "Примечание": ""
                    }]
                
                # Update session with all saved data
                session.update({
                    'start_date': sess_data.get('start_date', ''),
                    'end_date': sess_data.get('end_date', ''),
                    'rows_data': saved_rows,
                    'constant_fields': sess_data.get('constant_fields', {})
                })
                
                # Set the session ID to the loaded file's name (without extension)
                session['session_id'] = os.path.splitext(selected_file)[0]
                
            except Exception as e:
                print(f"Error loading session: {str(e)}")
                flash(f"Ошибка загрузки сессии: {str(e)}")
                return redirect(url_for("index"))
            flash(f"Сессия '{load_session_name}' успешно загружена")
            return redirect(url_for("index"))

        elif action == "new_session":
            # Очищаем сессию и добавляем пустую строку в таблицу
            session.clear()
            session['rows_data'] = [{
                "шаблон": "", "номер": "", "Наименование_работ": "", 
                "Начало": "", "Конец": "", 
                "Материалы_и_серты": "", "Схемы_и_тд": "", 
                "Разрешает_пр_во_работ_по": "", "СП": "", "selected": False
            }]
            flash("Новая сессия создана")
            return redirect(url_for("index"))
        
        # Если действие не распознано, возвращаемся на главную страницу
        return redirect(url_for("index"))
    
    except Exception as e:
        print(f"Error in process: {str(e)}")
        flash(f"Произошла ошибка: {str(e)}")
        return redirect(url_for("index"))

@app.route("/calculate_dates", methods=["POST"])
def calculate_dates():
    start_date = request.json.get("start_date", "")
    end_date = request.json.get("end_date", "")
    rows = int(request.json.get("rows", 0))
    
    if not start_date or not end_date:
        return jsonify({"success": False, "error": "Укажите дату начала и окончания работ"})
    
    try:
        start_dt = datetime.fromisoformat(start_date)
        end_dt = datetime.fromisoformat(end_date)
    except Exception:
        return jsonify({"success": False, "error": "Неправильный формат даты"})
    
    days = bdays_range(start_dt, end_dt)
    spans = split_business_days(days, rows)
    out = []
    for s, e in spans:
        if s is None or e is None:
            out.append({"start_date": "", "end_date": ""})
            continue
        out.append({
            "start_date": s.strftime("%Y-%m-%d"),
            "end_date": e.strftime("%Y-%m-%d")
        })
    
    return jsonify({"success": True, "dates": out})

if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5000)