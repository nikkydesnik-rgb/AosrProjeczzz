let currentSession = null;
let templatesCache = [];
let currentTemplateName = null;
let aosrHot = null;
let syncingFromHot = false;
let previewZoom = 1;
const DEFAULT_CONSTANT_KEYS = [
  "Объект",
  "Застройщик",
  "Строитель",
  "Проектная_организация",
  "Проект_или_ТЗ",
  "Представитель_застр",
  "ФИО_застр",
  "Распор_застр",
  "Пр_раб",
  "ФИО_Пр_раб",
  "Распор_пр_раб",
  "Строй_контроль_Должность",
  "ФИО_Стройк",
  "Распор_стройк",
  "Проектировщик_должность",
  "Проектировщик_ФИО",
  "Распоряжение_проект",
  "Выполнил_работы",
  "Иные_долж",
  "ФИО_Иные",
  "Распор_иные",
  "Организация_исполнитель",
  "Экз",
];

function ensureDefaultConstantFields(session) {
  if (!session) return;
  session.constant_fields = session.constant_fields || {};
  DEFAULT_CONSTANT_KEYS.forEach((key) => {
    if (!(key in session.constant_fields)) {
      session.constant_fields[key] = key === "Экз" ? "2" : "";
    }
  });
}

async function fetchText(path) {
  const res = await fetch(path);
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}: ${await res.text()}`);
  }
  return await res.text();
}

function setOutput(value) {
  const el = document.getElementById("output-log");
  el.textContent = typeof value === "string" ? value : JSON.stringify(value, null, 2);
}

function syncTextareaFromSession() {
  const ta = document.getElementById("session-json");
  if (ta) {
    ta.value = currentSession ? JSON.stringify(currentSession, null, 2) : "";
  }
  const inputName = document.getElementById("input-session-name");
  if (inputName) {
    const name = currentSession?.meta?.name || "";
    inputName.value = name;
  }
}

function syncSessionFromTextarea() {
  const ta = document.getElementById("session-json");
  if (!ta) return;
  const text = ta.value.trim();
  if (!text) {
    currentSession = null;
    return;
  }
  try {
    currentSession = JSON.parse(text);
  } catch (e) {
    setOutput("Не удалось распарсить JSON сессии: " + e.message);
  }
}

function getSessionJson() {
  if (!currentSession) {
    syncSessionFromTextarea();
  }
  return currentSession;
}

function flushEditorsToSession() {
}

function setSessionJson(obj) {
  currentSession = obj;
  ensureDefaultConstantFields(currentSession);
  syncTextareaFromSession();
  renderAllViews();
}

async function loadSampleSession() {
  try {
    const text = await fetchText("/sessions/sample_session.json");
    const data = JSON.parse(text);
    setSessionJson(data);
    setOutput("Загружен sample_session.json");
  } catch (e) {
    setOutput("Ошибка загрузки sample_session.json: " + e.message);
  }
}

async function loadSessionsList() {
  const select = document.getElementById("select-session-name");
  if (!select) return;
  try {
    const res = await fetch("/api/session/list");
    const data = await res.json();
    if (!res.ok || !Array.isArray(data)) {
      setOutput(data?.error || "Не удалось загрузить список сессий");
      return;
    }

    const parseSessionName = (name) => {
      const raw = String(name || "").trim();
      // Новый формат хранения: base__YYYY-MM-DD__HH-MM
      let m = raw.match(/^(.*)__(\d{4})-(\d{2})-(\d{2})__(\d{2})-(\d{2})$/);
      if (m) {
        const base = m[1];
        const yyyy = m[2];
        const mm = m[3];
        const dd = m[4];
        const hh = m[5];
        const mi = m[6];
        const iso = `${yyyy}-${mm}-${dd}T${hh}:${mi}:00`;
        const ts = Date.parse(iso);
        const label = `${base} ${dd}.${mm}.${yyyy} ${hh}:${mi}`;
        return { value: raw, label, ts: Number.isFinite(ts) ? ts : null };
      }

      // Старый формат: base_DD_MM_YYYY_HH_MM
      m = raw.match(/^(.*)_(\d{2})_(\d{2})_(\d{4})_(\d{2})_(\d{2})$/);
      if (m) {
        const base = m[1];
        const dd = m[2];
        const mm = m[3];
        const yyyy = m[4];
        const hh = m[5];
        const mi = m[6];
        const iso = `${yyyy}-${mm}-${dd}T${hh}:${mi}:00`;
        const ts = Date.parse(iso);
        const label = `${base} ${dd}.${mm}.${yyyy} ${hh}:${mi}`;
        return { value: raw, label, ts: Number.isFinite(ts) ? ts : null };
      }

      // Человеко-читаемый формат: base DD.MM.YYYY HH:MM
      m = raw.match(/^(.*)\s+(\d{2})\.(\d{2})\.(\d{4})\s+(\d{2}):(\d{2})$/);
      if (m) {
        const base = m[1];
        const dd = m[2];
        const mm = m[3];
        const yyyy = m[4];
        const hh = m[5];
        const mi = m[6];
        const iso = `${yyyy}-${mm}-${dd}T${hh}:${mi}:00`;
        const ts = Date.parse(iso);
        return { value: raw, label: raw, ts: Number.isFinite(ts) ? ts : null };
      }

      return { value: raw, label: raw, ts: null };
    };

    const sorted = data
      .map(parseSessionName)
      .sort((a, b) => {
        if (a.ts !== null && b.ts !== null) return b.ts - a.ts; // новые сверху
        if (a.ts !== null) return -1;
        if (b.ts !== null) return 1;
        return a.label.localeCompare(b.label, "ru");
      });

    select.innerHTML = "";
    sorted.forEach((item) => {
      const opt = document.createElement("option");
      opt.value = item.value;
      opt.textContent = item.label;
      select.appendChild(opt);
    });
    if (sorted.length === 0) {
      const opt = document.createElement("option");
      opt.value = "";
      opt.textContent = "Нет сохраненных сессий";
      select.appendChild(opt);
    }
  } catch (e) {
    setOutput("Ошибка загрузки списка сессий: " + e.message);
  }
}

async function saveSession() {
  try {
    flushEditorsToSession();
    const session = getSessionJson();
    if (!session) {
      setOutput("Нет данных сессии для сохранения");
      return;
    }
    const nameInput = document.getElementById("input-session-name");

    const stripTrailingStamps = (value) => {
      let out = String(value || "").trim();
      // Удаляем один или несколько хвостов дат:
      // 1) старый формат: _DD_MM_YYYY_HH_MM
      // 2) новый формат: " DD.MM.YYYY HH:MM"
      while (/_\d{2}_\d{2}_\d{4}_\d{2}_\d{2}$/.test(out) || /\s+\d{2}\.\d{2}\.\d{4}\s+\d{2}:\d{2}$/.test(out)) {
        out = out
          .replace(/_\d{2}_\d{2}_\d{4}_\d{2}_\d{2}$/, "")
          .replace(/\s+\d{2}\.\d{2}\.\d{4}\s+\d{2}:\d{2}$/, "");
      }
      return out.trim();
    };

    const rawName = nameInput?.value?.trim() || session?.meta?.name || "session";
    const baseNameRaw = stripTrailingStamps(rawName) || "session";

    const now = new Date();
    const dd = String(now.getDate()).padStart(2, "0");
    const mm = String(now.getMonth() + 1).padStart(2, "0");
    const yyyy = now.getFullYear();
    const hh = String(now.getHours()).padStart(2, "0");
    const min = String(now.getMinutes()).padStart(2, "0");
    const stamp = `${dd}.${mm}.${yyyy} ${hh}:${min}`;
    const fullName = `${baseNameRaw} ${stamp}`;

    session.meta = session.meta || {};
    session.meta.name = fullName;
    session.meta.created_at = now.toISOString();

    if (nameInput) {
      nameInput.value = fullName;
    }

    const body = {
      session,
      name: fullName,
    };
    const res = await fetch("/api/session/save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (res.ok) {
      try {
        localStorage.setItem("lastSessionName", data?.name || fullName);
      } catch (_) {}
      await loadSessionsList();
      setOutput("сессия сохранена");
      return;
    }
    setOutput(data);
  } catch (e) {
    setOutput("Ошибка сохранения: " + e.message);
  }
}

// --- Рендер вкладок --------------------------------------------------------

function renderConstants() {
  const session = getSessionJson();
  const tbody = document.querySelector("#constants-table tbody");
  if (!tbody) return;

  tbody.innerHTML = "";
  if (!session) return;

  const cf = session.constant_fields || {};
  Object.keys(cf).forEach((key) => {
    const tr = document.createElement("tr");
    tr.dataset.key = key;
    tr.innerHTML = `
      <td>${key}</td>
      <td>
        <input type="text" class="const-value" value="${cf[key] ?? ""}">
      </td>
      <td>
        <button type="button" class="btn-delete-const" title="Удалить">×</button>
      </td>
    `;
    tbody.appendChild(tr);
  });
}

function renderMaterials() {
  const session = getSessionJson();
  const tbody = document.querySelector("#materials-table tbody");
  if (!tbody) return;
  tbody.innerHTML = "";
  if (!session) return;
  const mats = session.materials || [];
  mats.forEach((m) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${m.row_id ?? ""}</td>
      <td>${m.name ?? ""}</td>
      <td>${m.qty ?? ""}</td>
      <td>${m.unit ?? ""}</td>
      <td>${m.document_name ?? ""}</td>
      <td>${m.validity ?? ""}</td>
    `;
    tbody.appendChild(tr);
  });
}

function renderAosr() {
  const tbody = document.querySelector("#aosr-table tbody");
  if (!tbody) return;
  tbody.innerHTML = "";
  if (!session) return;

  const docs = (session.documents || []).slice().sort((a, b) => (a.order || 0) - (b.order || 0));
  docs
    .filter((d) => (d.type || "").trim() === "АОСР")
    .forEach((d) => {
      const data = d.data || {};
      const tr = document.createElement("tr");
      tr.dataset.docId = d.id || "";
      tr.innerHTML = `
        <td>${d.order ?? ""}</td>
        <td>${d.id ?? ""}</td>
        <td>${d.title ?? ""}</td>
        <td><input type="text" class="aosr-cell-input" data-field="номер" value="${data.номер ?? ""}"></td>
        <td><textarea class="aosr-cell-textarea" data-field="Наименование_работ">${data.Наименование_работ ?? ""}</textarea></td>
        <td><textarea class="aosr-cell-textarea" data-field="Материалы_и_серты">${data.Материалы_и_серты ?? ""}</textarea></td>
        <td><textarea class="aosr-cell-textarea" data-field="Схемы_и_тд">${data.Схемы_и_тд ?? ""}</textarea></td>
        <td><textarea class="aosr-cell-textarea" data-field="Разрешает_пр_во_работ_по">${data.Разрешает_пр_во_работ_по ?? ""}</textarea></td>
        <td><textarea class="aosr-cell-textarea" data-field="СП">${data.СП ?? ""}</textarea></td>
        <td><input type="date" class="aosr-cell-input" data-field="start_date" value="${d.start_date ?? ""}"></td>
        <td><input type="date" class="aosr-cell-input" data-field="end_date" value="${d.end_date ?? ""}"></td>
        <td><input type="checkbox" class="aosr-cell-checkbox" data-field="manual_override" ${d.manual_override ? "checked" : ""}></td>
      `;
      tbody.appendChild(tr);
    });
}

function isoToRuDate(value) {
  const v = String(value || "").trim();
  if (!v) return "";
  const m = v.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!m) return v;
  return `${m[3]}.${m[2]}.${m[1]}`;
}

function ruToIsoDate(value) {
  const v = String(value || "").trim();
  if (!v) return null;
  const m = v.match(/^(\d{2})\.(\d{2})\.(\d{4})$/);
  if (!m) return null;
  return `${m[3]}-${m[2]}-${m[1]}`;
}

function buildAosrRowsFromSession(session) {
  if (!session) return [];
  const docs = (session.documents || [])
    .filter((d) => (d.type || "").trim() === "АОСР")
    .slice()
    .sort((a, b) => (a.order || 0) - (b.order || 0));

  return docs.map((d) => {
    const data = d.data || {};
    return {
      selected: false,
      шаблон: d.template || "",
      номер: data.номер || String(d.order || ""),
      Наименование_работ: data.Наименование_работ || "",
      Начало: data.Начало || isoToRuDate(d.start_date),
      Конец: data.Конец || isoToRuDate(d.end_date),
      Материалы_и_серты: data.Материалы_и_серты || "",
      Схемы_и_тд: data.Схемы_и_тд || "",
      Разрешает_пр_во_работ_по: data.Разрешает_пр_во_работ_по || "",
      СП: data.СП || "",
      _docId: d.id || "",
    };
  });
}

function syncSessionFromAosrHot() {
  if (!aosrHot || syncingFromHot) return;
  const session = getSessionJson();
  if (!session) return;

  const prevDocs = session.documents || [];
  const byId = new Map(prevDocs.map((d) => [d.id, d]));
  const nonAosr = prevDocs.filter((d) => (d.type || "").trim() !== "АОСР");

  const rows = aosrHot.getSourceData();
  const aosrDocs = [];
  rows.forEach((row, index) => {
    const isEmpty =
      !String(row?.шаблон || "").trim() &&
      !String(row?.номер || "").trim() &&
      !String(row?.Наименование_работ || "").trim() &&
      !String(row?.Материалы_и_серты || "").trim();
    if (isEmpty) return;

    const previous = byId.get(row._docId) || {};
    const parsedOrder = Number.parseInt(row.номер, 10);
    const order = Number.isFinite(parsedOrder) && parsedOrder > 0 ? parsedOrder : index + 1;
    const id = row._docId || previous.id || buildUniqueDocId({ documents: [...nonAosr, ...aosrDocs] }, "AOSR");
    const startIso = ruToIsoDate(row.Начало);
    const endIso = ruToIsoDate(row.Конец);

    aosrDocs.push({
      id,
      type: "АОСР",
      template: String(row.шаблон || "").trim(),
      title: `АОСР №${order}`,
      order,
      // Строки АОСР в таблице всегда участвуют в автопересчёте дат.
      manual_override: false,
      start_date: startIso,
      end_date: endIso,
      pages: Number(previous.pages) || 1,
      data: {
        номер: String(row.номер || order),
        Наименование_работ: String(row.Наименование_работ || ""),
        Начало: String(row.Начало || ""),
        Конец: String(row.Конец || ""),
        Материалы_и_серты: String(row.Материалы_и_серты || ""),
        Схемы_и_тд: String(row.Схемы_и_тд || ""),
        Разрешает_пр_во_работ_по: String(row.Разрешает_пр_во_работ_по || ""),
        СП: String(row.СП || ""),
      },
    });
  });

  session.documents = [...nonAosr, ...aosrDocs];
  syncAosrOrderByNumber(session);
}

function initAosrHot() {
  if (aosrHot) return;
  const container = document.getElementById("aosr-hot");
  if (!container || !window.Handsontable) return;

  aosrHot = new Handsontable(container, {
    data: [],
    stretchH: "all",
    rowHeaders: true,
    height: 360,
    colHeaders: [
      "✓",
      "Шаблон",
      "Номер",
      "Наименование работ",
      "Начало",
      "Конец",
      "Материалы и серты",
      "Схемы и тд",
      "Разрешает пр-во работ по",
      "СП",
    ],
    columns: [
      { data: "selected", type: "checkbox", width: 36 },
      { data: "шаблон", type: "dropdown", source: (templatesCache || []).map((t) => t.docx_name), width: 140 },
      { data: "номер", type: "text", width: 80 },
      { data: "Наименование_работ", type: "text", width: 220 },
      { data: "Начало", type: "date", dateFormat: "DD.MM.YYYY", correctFormat: true, width: 120 },
      { data: "Конец", type: "date", dateFormat: "DD.MM.YYYY", correctFormat: true, width: 120 },
      { data: "Материалы_и_серты", type: "text", width: 220 },
      { data: "Схемы_и_тд", type: "text", width: 180 },
      { data: "Разрешает_пр_во_работ_по", type: "text", width: 230 },
      { data: "СП", type: "text", width: 190 },
    ],
    contextMenu: true,
    manualColumnResize: true,
    licenseKey: "non-commercial-and-evaluation",
    afterChange(changes, source) {
      if (!changes || source === "loadData") return;
      syncSessionFromAosrHot();
      renderRegistry();
      syncTextareaFromSession();
    },
  });
}

function renderOtherDocs() {
  const session = getSessionJson();
  const tbody = document.querySelector("#other-table tbody");
  if (!tbody) return;
  tbody.innerHTML = "";
  if (!session) return;
  const docs = (session.documents || []).slice().sort((a, b) => (a.order || 0) - (b.order || 0));
  docs
    .filter((d) => (d.type || "").trim() !== "АОСР")
    .forEach((d) => {
      const date =
        d.date || d.end_date || d.start_date || "";
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${d.order ?? ""}</td>
        <td>${d.id ?? ""}</td>
        <td>${d.type ?? ""}</td>
        <td>${d.title ?? ""}</td>
        <td>${date}</td>
      `;
      tbody.appendChild(tr);
    });
}

function renderAttachments() {
  const session = getSessionJson();
  const tbody = document.querySelector("#attachments-table tbody");
  if (!tbody) return;
  tbody.innerHTML = "";
  if (!session) return;
  const atts = session.attachments || [];
  atts.forEach((a) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${a.id ?? ""}</td>
      <td>${a.path ?? ""}</td>
      <td>${a.type ?? ""}</td>
      <td>${a.order ?? ""}</td>
    `;
    tbody.appendChild(tr);
  });
}

function renderRegistry() {
  const session = getSessionJson();
  const tbody = document.querySelector("#registry-table tbody");
  if (!tbody) return;
  tbody.innerHTML = "";
  if (!session) return;
  const docs = (session.documents || []).slice().sort((a, b) => (a.order || 0) - (b.order || 0));
  docs.forEach((d) => {
    const tr = document.createElement("tr");
    const fileLogical = `${String(d.order ?? 0).padStart(2, "0")}_${d.type || "DOC"}_${(d.title || "").replace(/\s+/g, "_")}`;
    tr.innerHTML = `
      <td>${d.order ?? ""}</td>
      <td>${d.id ?? ""}</td>
      <td>${d.title ?? ""}</td>
      <td>${d.end_date ?? ""}</td>
      <td>${fileLogical}</td>
    `;
    tbody.appendChild(tr);
  });
}

function renderAllViews() {
  syncTextareaFromSession();
  renderConstants();
  renderMaterials();
  renderAosr();
  renderOtherDocs();
  renderAttachments();
  renderRegistry();
}

async function loadSessionByName(name) {
  const res = await fetch("/api/session/load", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  const data = await res.json();
  if (!res.ok) {
    throw new Error(JSON.stringify(data));
  }
  setSessionJson(data);
  const select = document.getElementById("select-session-name");
  if (select && name) {
    select.value = name;
  }
}

async function loadLastOrSampleSession() {
  let loaded = false;
  try {
    const lastName = localStorage.getItem("lastSessionName");
    if (lastName) {
      await loadSessionByName(lastName);
      setOutput(`Загружена последняя сохранённая сессия: ${lastName}`);
      loaded = true;
    }
  } catch (_) {
    // игнорируем и падаем на sample
  }
  if (!loaded) {
    await loadSampleSession();
  }
}

// --- Шаблоны ---------------------------------------------------------------

async function loadTemplates() {
  try {
    const res = await fetch("/api/templates/list");
    const data = await res.json();
    if (!res.ok) {
      setOutput(data);
      return;
    }
    templatesCache = data;
    renderTemplates();
    if (aosrHot) {
      aosrHot.updateSettings({
        columns: [
          { data: "selected", type: "checkbox", width: 36 },
          { data: "шаблон", type: "dropdown", source: (templatesCache || []).map((t) => t.docx_name), width: 140 },
          { data: "номер", type: "text", width: 80 },
          { data: "Наименование_работ", type: "text", width: 220 },
          { data: "Начало", type: "date", dateFormat: "DD.MM.YYYY", correctFormat: true, width: 120 },
          { data: "Конец", type: "date", dateFormat: "DD.MM.YYYY", correctFormat: true, width: 120 },
          { data: "Материалы_и_серты", type: "text", width: 220 },
          { data: "Схемы_и_тд", type: "text", width: 180 },
          { data: "Разрешает_пр_во_работ_по", type: "text", width: 230 },
          { data: "СП", type: "text", width: 190 },
        ],
      });
    }
  } catch (e) {
    setOutput("Ошибка загрузки шаблонов: " + e.message);
  }
}

function renderTemplates() {
  const tbody = document.querySelector("#templates-table tbody");
  if (!tbody) return;
  tbody.innerHTML = "";
  (templatesCache || []).forEach((t) => {
    const tr = document.createElement("tr");
    const hasMeta = !!t.has_metadata;
    tr.innerHTML = `
      <td>${t.docx_name}</td>
      <td>${t.metadata?.display_name || ""}</td>
      <td>${t.metadata?.type || ""}</td>
      <td>${hasMeta ? "Да" : "Нет"}</td>
      <td>
        <button type="button" class="btn-add-template" data-docx="${t.docx_name}" ${hasMeta ? "" : "disabled"}>
          Добавить в реестр
        </button>
      </td>
      <td>
        <button type="button" class="btn-build-meta" data-docx="${t.docx_name}">
          ${hasMeta ? "Пересоздать" : "Сгенерировать"} metadata
        </button>
      </td>
    `;
    tbody.appendChild(tr);
  });
}


function getTemplateFieldScopes(meta) {
  const fields = meta?.fields || {};
  const allKeys = Object.keys(fields);
  const constantKeysFromMeta = Array.isArray(meta?.constant_fields_order) ? meta.constant_fields_order : [];
  const docKeysFromMeta = Array.isArray(meta?.doc_fields_order) ? meta.doc_fields_order : [];

  const normalize = (v) => String(v || "").trim();
  const known = new Set(allKeys);

  const constantKeys = constantKeysFromMeta.map(normalize).filter((k) => k && known.has(k));
  const docKeys = docKeysFromMeta.map(normalize).filter((k) => k && known.has(k));

  // fallback для старых metadata без разделения
  if (constantKeys.length === 0 && docKeys.length === 0) {
    const knownConstant = new Set([
      "Объект", "Застройщик", "Строитель", "Проектная_организация", "Проект_или_ТЗ",
      "Представитель_застр", "ФИО_застр", "Распор_застр", "Пр_раб", "ФИО_Пр_раб",
      "Распор_пр_раб", "Строй_контроль_Должность", "ФИО_Стройк", "Распор_стройк",
      "Проектировщик_должность", "Проектировщик_ФИО", "Распоряжение_проект", "Выполнил_работы",
      "Иные_долж", "ФИО_Иные", "Распор_иные", "Организация_исполнитель", "Экз",
    ]);
    const knownDoc = new Set([
      "номер", "Наименование_работ", "Начало", "Конец", "Материалы_и_серты", "Схемы_и_тд",
      "Разрешает_пр_во_работ_по", "СП", "Ч", "М", "Г", "Чнач", "Мнач", "Гн", "date_end",
    ]);
    const docSpecificWords = ["материал", "серт", "прилож", "схем", "черт", "испыт", "наименование_работ"];

    const guessedConst = [];
    const guessedDoc = [];
    allKeys.forEach((key) => {
      if (knownConstant.has(key)) {
        guessedConst.push(key);
        return;
      }
      if (knownDoc.has(key)) {
        guessedDoc.push(key);
        return;
      }
      const low = key.toLowerCase();
      const isDocSpecific = docSpecificWords.some((w) => low.includes(w));
      if (isDocSpecific) {
        guessedDoc.push(key);
      } else {
        guessedConst.push(key);
      }
    });
    return { allKeys, constantKeys: guessedConst, docKeys: guessedDoc };
  }

  // если один из списков пуст, достраиваем остатком полей в исходном порядке
  const used = new Set([...constantKeys, ...docKeys]);
  allKeys.forEach((key) => {
    if (used.has(key)) return;
    if (constantKeys.length === 0) {
      constantKeys.push(key);
    } else {
      docKeys.push(key);
    }
  });

  return { allKeys, constantKeys, docKeys };
}

function mergeTemplateFieldsToConstantFields(fieldKeys) {
  if (!fieldKeys || fieldKeys.length === 0) return;
  const session = getSessionJson() || {};
  const cf = session.constant_fields || {};
  const newCf = {};

  // Сначала ключи из шаблона, в порядке появления
  fieldKeys.forEach((key) => {
    newCf[key] = key in cf ? cf[key] : "";
  });

  // Затем все прочие ключи, которые уже были в сессии
  Object.keys(cf).forEach((key) => {
    if (!fieldKeys.includes(key)) {
      newCf[key] = cf[key];
    }
  });

  session.constant_fields = newCf;
  setSessionJson(session);
}

function nextDocumentOrder(session) {
  const docs = session.documents || [];
  if (docs.length === 0) return 1;
  const maxOrder = docs.reduce((acc, d) => Math.max(acc, Number(d.order) || 0), 0);
  return maxOrder + 1;
}

function buildUniqueDocId(session, prefix) {
  const normalizedPrefix = (prefix || "DOC").replace(/\s+/g, "_").toUpperCase();
  const used = new Set((session.documents || []).map((d) => d.id));
  let idx = 1;
  let candidate = `${normalizedPrefix}_${idx}`;
  while (used.has(candidate)) {
    idx += 1;
    candidate = `${normalizedPrefix}_${idx}`;
  }
  return candidate;
}

function syncAosrOrderByNumber(session) {
  const docs = session.documents || [];
  docs.forEach((doc) => {
    if ((doc.type || "").trim() !== "АОСР") return;
    const n = Number.parseInt(doc?.data?.номер, 10);
    if (Number.isFinite(n) && n > 0) {
      doc.order = n;
      if (!doc.title || /^АОСР\s*№/i.test(doc.title)) {
        doc.title = `АОСР №${n}`;
      }
    }
  });
}

function detectAosrTemplateName(session) {
  const docs = session.documents || [];
  const existingAosr = docs.find((d) => (d.type || "").trim() === "АОСР" && d.template);
  if (existingAosr?.template) return existingAosr.template;

  const fromCache = (templatesCache || []).find((t) => (t.metadata?.type || "").trim() === "АОСР");
  if (fromCache?.docx_name) return fromCache.docx_name;

  return "";
}

function addAosrRow() {
  const session = getSessionJson() || {};
  session.documents = session.documents || [];

  const nextNumber = (session.documents || [])
    .filter((d) => (d.type || "").trim() === "АОСР")
    .reduce((acc, d) => Math.max(acc, Number.parseInt(d?.data?.номер, 10) || 0), 0) + 1;

  const doc = {
    id: buildUniqueDocId(session, "AOSR"),
    type: "АОСР",
    template: detectAosrTemplateName(session),
    title: `АОСР №${nextNumber}`,
    order: nextNumber,
    manual_override: false,
    start_date: null,
    end_date: null,
    pages: 1,
    data: {
      номер: String(nextNumber),
      Наименование_работ: "",
      Материалы_и_серты: "",
      Схемы_и_тд: "",
      Разрешает_пр_во_работ_по: "",
      СП: "",
    },
  };

  session.documents.push(doc);
  syncAosrOrderByNumber(session);
  setSessionJson(session);
  setOutput(`Добавлен акт АОСР №${nextNumber}`);
}

function addTemplateToRegistry(docxName) {
  const template = (templatesCache || []).find((t) => t.docx_name === docxName);
  if (!template || !template.metadata) {
    setOutput("Для добавления в реестр сначала сгенерируйте metadata шаблона.");
    return;
  }

  const session = getSessionJson() || {};
  session.documents = session.documents || [];

  const meta = template.metadata;
  let count = 1;
  if (meta.multiple) {
    const answer = window.prompt(`Шаблон «${meta.display_name || docxName}» допускает множественные документы. Сколько добавить?`, "1");
    if (answer === null) return;
    count = Math.max(1, Number.parseInt(answer, 10) || 1);
  }

  const { allKeys, constantKeys, docKeys } = getTemplateFieldScopes(meta);
  mergeTemplateFieldsToConstantFields(constantKeys);

  for (let i = 0; i < count; i += 1) {
    const order = nextDocumentOrder(session);
    const seq = i + 1;
    const data = {};
    const docDataKeys = docKeys.length > 0 ? docKeys : allKeys;
    docDataKeys.forEach((key) => {
      data[key] = "";
    });
    if ("номер" in data) {
      data.номер = String(order);
    }

    const type = meta.type || "GENERIC";
    const titleBase = meta.display_name || docxName.replace(/\.docx$/i, "");
    const title = count > 1 ? `${titleBase} №${seq}` : titleBase;

    session.documents.push({
      id: buildUniqueDocId(session, meta.prefix || type || "DOC"),
      type,
      template: docxName,
      title,
      order,
      manual_override: false,
      start_date: null,
      end_date: null,
      pages: Number(meta.default_pages) || 1,
      data,
    });
  }

  syncAosrOrderByNumber(session);
  setSessionJson(session);
  setOutput(`Добавлено документов по шаблону: ${count}`);
}

async function buildMetadataForTemplate(docxName) {
  try {
    const res = await fetch("/api/templates/build_metadata", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ template_name: docxName }),
    });
    const data = await res.json();
    if (!res.ok) {
      setOutput(data);
      return;
    }
    currentTemplateName = data.template_name;
    const ta = document.getElementById("template-meta-text");
    if (ta) {
      ta.value = JSON.stringify(data.metadata, null, 2);
    }
    const btnSave = document.getElementById("btn-save-template-meta");
    if (btnSave) {
      btnSave.disabled = false;
    }

    // Автоматически добавляем вытянутые ключи в блок "Постоянные данные"
    // и переупорядочиваем их в том порядке, как они идут в шаблоне.
    const scopes = getTemplateFieldScopes(data.metadata || {});
    mergeTemplateFieldsToConstantFields(scopes.constantKeys);

    setOutput(`Metadata сгенерированы для ${docxName}`);
  } catch (e) {
    setOutput("Ошибка генерации metadata: " + e.message);
  }
}

async function saveCurrentTemplateMetadata() {
  try {
    const ta = document.getElementById("template-meta-text");
    if (!ta) return;
    const text = ta.value.trim();
    if (!text) {
      setOutput("Поле metadata пустое");
      return;
    }
    let meta;
    try {
      meta = JSON.parse(text);
    } catch (e) {
      setOutput("Ошибка парсинга metadata JSON: " + e.message);
      return;
    }
    if (!currentTemplateName) {
      setOutput("Не выбран шаблон для сохранения metadata");
      return;
    }
    const res = await fetch("/api/templates/save_metadata", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        template_name: currentTemplateName,
        metadata: meta,
      }),
    });
    const data = await res.json();
    setOutput(data);
    if (res.ok) {
      await loadTemplates();
    }
  } catch (e) {
    setOutput("Ошибка сохранения metadata: " + e.message);
  }
}

async function calculateDates() {
  try {
    flushEditorsToSession();
    const session = getSessionJson();
    if (!session) {
      setOutput("Нет данных сессии для перерасчёта");
      return;
    }
    const globalStart = document.getElementById("input-global-start").value || null;
    const globalEnd = document.getElementById("input-global-end").value || null;

    const body = {
      session,
      global_start: globalStart,
      global_end: globalEnd,
    };

    const res = await fetch("/api/dates/calculate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (res.ok) {
      setSessionJson(data);
      setOutput("Даты пересчитаны.");
    } else {
      setOutput(data);
    }
  } catch (e) {
    setOutput("Ошибка перерасчёта дат: " + e.message);
  }
}

async function generateDocuments() {
  try {
    flushEditorsToSession();
    const session = getSessionJson();
    if (!session) {
      setOutput("Нет данных сессии для генерации");
      return;
    }
    const mergePdf = document.getElementById("chk-merge-pdf").checked;
    const body = { session, merge_pdf: mergePdf };

    const res = await fetch("/api/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    setOutput(data);
  } catch (e) {
    setOutput("Ошибка генерации: " + e.message);
  }
}

async function previewDocument() {
  try {
    flushEditorsToSession();
    const session = getSessionJson();
    if (!session) {
      setOutput("Нет данных сессии для предпросмотра");
      return;
    }
    const docId = document.getElementById("input-doc-id").value.trim();
    if (!docId) {
      setOutput("Укажите doc_id");
      return;
    }
    const body = { session, doc_id: docId };

    const res = await fetch("/api/preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) {
      setOutput(data);
      return;
    }
    const url = data?.preview_url;
    if (!url) {
      setOutput("Предпросмотр сгенерирован, но ссылка не получена");
      return;
    }
    showPreview(url);
    setOutput("Предпросмотр открыт справа.");
  } catch (e) {
    setOutput("Ошибка предпросмотра: " + e.message);
  }
}

function applyPreviewZoom() {
  const iframe = document.getElementById("preview-iframe");
  if (!iframe) return;
  iframe.style.transform = `scale(${previewZoom})`;
  iframe.style.width = `${100 / previewZoom}%`;
}

function showPreview(url) {
  const panel = document.getElementById("preview-panel");
  const iframe = document.getElementById("preview-iframe");
  if (!panel || !iframe) return;
  panel.classList.remove("hidden");
  previewZoom = 1;
  applyPreviewZoom();
  iframe.src = `${url}${url.includes("?") ? "&" : "?"}t=${Date.now()}`;
}

window.addEventListener("DOMContentLoaded", () => {
  const layout = document.querySelector("main.layout");
  const btnToggleControls = document.getElementById("btn-toggle-controls");
  if (layout && btnToggleControls) {
    const key = "controlsCollapsed";
    const applyState = (collapsed) => {
      layout.classList.toggle("collapsed-controls", collapsed);
      btnToggleControls.textContent = collapsed ? "▶" : "◀";
      btnToggleControls.title = collapsed ? "Развернуть панель" : "Свернуть панель";
    };
    let collapsed = false;
    try {
      collapsed = localStorage.getItem(key) === "1";
    } catch (_) {}
    applyState(collapsed);
    btnToggleControls.addEventListener("click", () => {
      collapsed = !layout.classList.contains("collapsed-controls");
      applyState(collapsed);
      try {
        localStorage.setItem(key, collapsed ? "1" : "0");
      } catch (_) {}
    });
  }

  const btnSaveSession = document.getElementById("btn-save-session");
  if (btnSaveSession) btnSaveSession.addEventListener("click", saveSession);
  const btnCalcDates = document.getElementById("btn-calc-dates");
  if (btnCalcDates) btnCalcDates.addEventListener("click", calculateDates);
  const btnGenerate = document.getElementById("btn-generate");
  if (btnGenerate) btnGenerate.addEventListener("click", generateDocuments);
  const btnPreview = document.getElementById("btn-preview");
  if (btnPreview) btnPreview.addEventListener("click", previewDocument);
  const btnPreviewZoomIn = document.getElementById("btn-preview-zoom-in");
  const btnPreviewZoomOut = document.getElementById("btn-preview-zoom-out");
  const btnPreviewZoomReset = document.getElementById("btn-preview-zoom-reset");
  const btnPreviewHide = document.getElementById("btn-preview-hide");
  if (btnPreviewZoomIn) {
    btnPreviewZoomIn.addEventListener("click", () => {
      previewZoom = Math.min(2.5, previewZoom + 0.1);
      applyPreviewZoom();
    });
  }
  if (btnPreviewZoomOut) {
    btnPreviewZoomOut.addEventListener("click", () => {
      previewZoom = Math.max(0.5, previewZoom - 0.1);
      applyPreviewZoom();
    });
  }
  if (btnPreviewZoomReset) {
    btnPreviewZoomReset.addEventListener("click", () => {
      previewZoom = 1;
      applyPreviewZoom();
    });
  }
  if (btnPreviewHide) {
    btnPreviewHide.addEventListener("click", () => {
      const panel = document.getElementById("preview-panel");
      if (panel) panel.classList.add("hidden");
    });
  }

  // Вкладки
  document.querySelectorAll(".tab-button").forEach((btn) => {
    btn.addEventListener("click", () => {
      const tab = btn.dataset.tab;
      document.querySelectorAll(".tab-button").forEach((b) => b.classList.toggle("active", b === btn));
      document.querySelectorAll(".tab-panel").forEach((panel) => {
        panel.classList.toggle("active", panel.id === `tab-${tab}`);
      });
      if (tab === "templates") {
        loadTemplates();
      }
    });
  });

  // Редактирование постоянных данных
  const constTable = document.getElementById("constants-table");
  if (constTable) {
    constTable.addEventListener("input", (e) => {
      const target = e.target;
      if (target.classList.contains("const-value")) {
        const tr = target.closest("tr");
        const key = tr?.dataset.key;
        const session = getSessionJson();
        if (session && key) {
          session.constant_fields = session.constant_fields || {};
          session.constant_fields[key] = target.value;
          setSessionJson(session);
        }
      }
    });
    constTable.addEventListener("click", (e) => {
      const target = e.target;
      if (target.classList.contains("btn-delete-const")) {
        const tr = target.closest("tr");
        const key = tr?.dataset.key;
        const session = getSessionJson();
        if (session && key) {
          if (session.constant_fields) {
            delete session.constant_fields[key];
          }
          setSessionJson(session);
        }
      }
    });
  }

  const aosrTable = document.getElementById("aosr-table");
  if (aosrTable) {
    const updateAosrField = (target) => {
      const tr = target.closest("tr");
      const docId = tr?.dataset.docId;
      const field = target.dataset.field;
      if (!docId || !field) return;

      const session = getSessionJson();
      if (!session) return;

      const doc = (session.documents || []).find((d) => d.id === docId);
      if (!doc) return;

      if (field === "start_date" || field === "end_date") {
        doc[field] = target.value || null;
      } else if (field === "manual_override") {
        doc.manual_override = !!target.checked;
      } else {
        doc.data = doc.data || {};
        doc.data[field] = target.value;
        if (field === "номер") {
          const n = Number.parseInt(target.value, 10);
          if (Number.isFinite(n) && n > 0) {
            doc.order = n;
            doc.title = `АОСР №${n}`;
          }
        }
      }

      syncAosrOrderByNumber(session);
      setSessionJson(session);
    };

    aosrTable.addEventListener("change", (e) => {
      const target = e.target;
      if (target.matches(".aosr-cell-input, .aosr-cell-textarea, .aosr-cell-checkbox")) {
        updateAosrField(target);
      }
    });

    aosrTable.addEventListener("blur", (e) => {
      const target = e.target;
      if (target.matches(".aosr-cell-input, .aosr-cell-textarea")) {
        updateAosrField(target);
      }
    }, true);
  }

  const btnAddAosrRow = document.getElementById("btn-add-aosr-row");
  if (btnAddAosrRow) {
    btnAddAosrRow.addEventListener("click", addAosrRow);
  }

  const btnAddConst = document.getElementById("btn-add-const");
  if (btnAddConst) {
    btnAddConst.addEventListener("click", () => {
      const keyInput = document.getElementById("const-new-key");
      const valInput = document.getElementById("const-new-value");
      const key = keyInput.value.trim();
      if (!key) return;
      const session = getSessionJson() || {};
      session.constant_fields = session.constant_fields || {};
      session.constant_fields[key] = valInput.value;
      setSessionJson(session);
      keyInput.value = "";
      valInput.value = "";
    });
  }

  const taJson = document.getElementById("session-json");
  if (taJson) {
    taJson.addEventListener("blur", () => {
      syncSessionFromTextarea();
      renderAllViews();
    });
  }

  const btnSaveMeta = document.getElementById("btn-save-template-meta");
  if (btnSaveMeta) {
    btnSaveMeta.addEventListener("click", saveCurrentTemplateMetadata);
  }

  const templatesTable = document.getElementById("templates-table");
  if (templatesTable) {
    templatesTable.addEventListener("click", (e) => {
      const target = e.target;
      if (target.classList.contains("btn-build-meta")) {
        const docx = target.dataset.docx;
        if (docx) {
          buildMetadataForTemplate(docx);
        }
      }
      if (target.classList.contains("btn-add-template")) {
        const docx = target.dataset.docx;
        if (docx) {
          addTemplateToRegistry(docx);
        }
      }
    });
  }

  const btnLoadSession = document.getElementById("btn-load-session");
  if (btnLoadSession) {
    btnLoadSession.addEventListener("click", async () => {
      const select = document.getElementById("select-session-name");
      const name = select?.value?.trim();
      if (!name) {
        setOutput("Выберите сессию для загрузки");
        return;
      }
      try {
        await loadSessionByName(name);
        setOutput(`Сессия загружена: ${name}`);
        try {
          localStorage.setItem("lastSessionName", name);
        } catch (_) {}
      } catch (e) {
        setOutput("Ошибка загрузки сессии: " + e.message);
      }
    });
  }

  const btnNewSession = document.getElementById("btn-new-session");
  if (btnNewSession) {
    btnNewSession.addEventListener("click", () => {
      const now = new Date();
      const dd = String(now.getDate()).padStart(2, "0");
      const mm = String(now.getMonth() + 1).padStart(2, "0");
      const yyyy = now.getFullYear();
      const hh = String(now.getHours()).padStart(2, "0");
      const min = String(now.getMinutes()).padStart(2, "0");
      const stamp = `${dd}.${mm}.${yyyy} ${hh}:${min}`;
      const baseName = "Новая сессия";
      const fullName = `${baseName} ${stamp}`;

      currentSession = {
        meta: {
          session_id: "",
          name: fullName,
          created_at: now.toISOString(),
        },
        constant_fields: {},
        documents: [],
        materials: [],
        attachments: [],
        settings: {},
      };
      try {
        localStorage.removeItem("lastSessionName");
      } catch (_) {}
      ensureDefaultConstantFields(currentSession);
      renderAllViews();
      setOutput("Создана новая пустая сессия.");
    });
  }

  // Автозагрузка: сначала список сессий и последняя сохранённая, иначе sample.
  loadTemplates();
  loadSessionsList().then(() => loadLastOrSampleSession());
});
