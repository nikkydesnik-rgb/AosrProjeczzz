let currentSession = null;
let templatesCache = [];
let currentTemplateName = null;
let aosrHot = null;
let syncingFromHot = false;

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

function buildSessionTimestamp(now = new Date()) {
  const dd = String(now.getDate()).padStart(2, "0");
  const mm = String(now.getMonth() + 1).padStart(2, "0");
  const yyyy = now.getFullYear();
  const hh = String(now.getHours()).padStart(2, "0");
  const min = String(now.getMinutes()).padStart(2, "0");
  return `${dd}.${mm}.${yyyy} ${hh}:${min}`;
}

function stripSessionTimestamp(name) {
  return String(name || "").replace(/\s\d{2}\.\d{2}\.\d{4}\s\d{2}:\d{2}$/, "").trim();
}

async function loadSessionOptions(selectedName = "") {
  const select = document.getElementById("select-sessions");
  if (!select) return;
  try {
    const res = await fetch("/api/session/list");
    const data = await res.json();
    if (!res.ok) throw new Error(data?.error || "Ошибка загрузки списка сессий");
    const items = Array.isArray(data?.items) ? data.items : [];
    select.innerHTML = "";
    items.forEach((name) => {
      const opt = document.createElement("option");
      opt.value = name;
      opt.textContent = name;
      select.appendChild(opt);
    });
    if (selectedName) {
      select.value = selectedName;
    }
  } catch (e) {
    setOutput("Не удалось загрузить список сессий: " + e.message);
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
  syncSessionFromAosrHot();
}

function setSessionJson(obj) {
  currentSession = obj;
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

async function saveSession() {
  try {
    flushEditorsToSession();
    const session = getSessionJson();
    if (!session) {
      setOutput("Нет данных сессии для сохранения");
      return;
    }
    const nameInput = document.getElementById("input-session-name");
    const currentName = session?.meta?.name || "";
    const inputNameValue = nameInput?.value?.trim() || "";
    const baseNameRaw = stripSessionTimestamp(inputNameValue || currentName || "session");
    const now = new Date();
    const stamp = buildSessionTimestamp(now);
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
      const pathParts = String(data?.path || "").split("/").filter(Boolean);
      const savedName = pathParts[pathParts.length - 1] === "session.json"
        ? pathParts[pathParts.length - 2]
        : (pathParts[pathParts.length - 1] || "").replace(/\.json$/i, "") || fullName;
      try {
        localStorage.setItem("lastSessionName", savedName);
      } catch (_) {}
      await loadSessionOptions(savedName);
      setOutput("Сессия сохранена.");
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
  initAosrHot();
  if (!aosrHot) return;
  syncingFromHot = true;
  aosrHot.loadData(buildAosrRowsFromSession(getSessionJson()));
  syncingFromHot = false;
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
      manual_override: true,
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
      "Приложения",
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

function ensureRegistryRows(session) {
  session.registry_rows = Array.isArray(session.registry_rows) ? session.registry_rows : [];
  const byDocId = new Map(session.registry_rows.map((r) => [r.doc_id, r]));
  const docs = (session.documents || []).slice().sort((a, b) => (a.order || 0) - (b.order || 0));
  const rows = docs.map((d, idx) => {
    const prev = byDocId.get(d.id) || {};
    return {
      doc_id: d.id || "",
      status: prev.status || "yellow",
      number: idx + 1,
      title: prev.title || d.title || "",
      num_date: prev.num_date || d.date || d.end_date || "",
      org: prev.org || session.constant_fields?.Строитель || "",
      pages: prev.pages || d.pages || 1,
      sheet: prev.sheet || idx + 1,
      file: prev.file || d.template || "",
    };
  });
  session.registry_rows = rows;
}

function renderRegistry() {
  const session = getSessionJson();
  const tbody = document.querySelector("#registry-table tbody");
  const objectLine = document.getElementById("registry-object-line");
  if (!tbody) return;
  tbody.innerHTML = "";
  if (!session) return;
  if (objectLine) {
    objectLine.textContent = `Объект: ${session?.constant_fields?.Объект || "—"}`;
  }
  ensureRegistryRows(session);
  (session.registry_rows || []).forEach((r, idx) => {
    const tr = document.createElement("tr");
    tr.className = `registry-status-${r.status || "yellow"}`;
    tr.dataset.index = String(idx);
    tr.innerHTML = `
      <td>
        <button type="button" class="btn-reg-up">↑</button>
        <button type="button" class="btn-reg-down">↓</button>
      </td>
      <td>
        <select class="reg-input" data-field="status">
          <option value="green" ${r.status === "green" ? "selected" : ""}>🟢</option>
          <option value="yellow" ${r.status === "yellow" ? "selected" : ""}>🟡</option>
          <option value="red" ${r.status === "red" ? "selected" : ""}>🔴</option>
        </select>
      </td>
      <td><input class="reg-input" data-field="number" value="${r.number ?? ""}"></td>
      <td><input class="reg-input" data-field="title" value="${r.title ?? ""}"></td>
      <td><input class="reg-input" data-field="num_date" value="${r.num_date ?? ""}"></td>
      <td><input class="reg-input" data-field="org" value="${r.org ?? ""}"></td>
      <td><input class="reg-input" data-field="pages" value="${r.pages ?? ""}"></td>
      <td><input class="reg-input" data-field="sheet" value="${r.sheet ?? ""}"></td>
      <td><input class="reg-input" data-field="file" value="${r.file ?? ""}"></td>
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
  await loadSessionOptions(localStorage.getItem("lastSessionName") || "");
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

async function ensureTemplatesCacheLoaded() {
  if ((templatesCache || []).length > 0) return templatesCache;
  try {
    const res = await fetch("/api/templates/list");
    const data = await res.json();
    if (res.ok && Array.isArray(data)) {
      templatesCache = data;
      return templatesCache;
    }
  } catch (e) {
    // noop: обработаем fallback в detectAosrTemplateName
  }
  return templatesCache || [];
}

async function detectAosrTemplateName(session) {
  const docs = session.documents || [];
  const existingAosr = docs.find((d) => (d.type || "").trim() === "АОСР" && d.template);
  if (existingAosr?.template) return existingAosr.template;

  await ensureTemplatesCacheLoaded();
  const fromCache = (templatesCache || []).find((t) => (t.metadata?.type || "").trim() === "АОСР");
  if (fromCache?.docx_name) return fromCache.docx_name;

  const byName = (templatesCache || []).find((t) => /aosr|аоср/i.test(String(t.docx_name || "")));
  if (byName?.docx_name) return byName.docx_name;

  const withMetadata = (templatesCache || []).find((t) => !!t.has_metadata && !!t.docx_name);
  if (withMetadata?.docx_name) return withMetadata.docx_name;

  const anyTemplate = (templatesCache || []).find((t) => !!t.docx_name);
  if (anyTemplate?.docx_name) return anyTemplate.docx_name;

  return "";
}

async function addAosrRow() {
  const session = getSessionJson() || {};
  session.documents = session.documents || [];

  const nextNumber = (session.documents || [])
    .filter((d) => (d.type || "").trim() === "АОСР")
    .reduce((acc, d) => Math.max(acc, Number.parseInt(d?.data?.номер, 10) || 0), 0) + 1;

  const doc = {
    id: buildUniqueDocId(session, "AOSR"),
    type: "АОСР",
    template: await detectAosrTemplateName(session),
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

  if (!doc.template) {
    setOutput("Не найдено ни одного шаблона .docx для АОСР: добавьте шаблон в папку templates.");
    return;
  }

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
    setOutput(data);
  } catch (e) {
    setOutput("Ошибка предпросмотра: " + e.message);
  }
}

window.addEventListener("DOMContentLoaded", () => {
  document.getElementById("btn-load-sample").addEventListener("click", loadSampleSession);
  document.getElementById("btn-save-session").addEventListener("click", saveSession);
  document.getElementById("btn-calc-dates").addEventListener("click", calculateDates);
  document.getElementById("btn-generate").addEventListener("click", generateDocuments);
  document.getElementById("btn-preview").addEventListener("click", previewDocument);

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

  const btnAddAosrRow = document.getElementById("btn-add-aosr-row");
  if (btnAddAosrRow) {
    btnAddAosrRow.addEventListener("click", addAosrRow);
  }

  const btnDeleteAosrSelected = document.getElementById("btn-delete-aosr-selected");
  if (btnDeleteAosrSelected) {
    btnDeleteAosrSelected.addEventListener("click", () => {
      if (!aosrHot) return;
      const rows = aosrHot.getSourceData();
      const filtered = rows.filter((r) => !r.selected);
      syncingFromHot = true;
      aosrHot.loadData(filtered);
      syncingFromHot = false;
      syncSessionFromAosrHot();
      renderAllViews();
      setOutput("Отмеченные строки АОСР удалены.");
    });
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

  const btnLoadFile = document.getElementById("btn-load-file");
  const fileInput = document.getElementById("file-input-session");
  if (btnLoadFile && fileInput) {
    btnLoadFile.addEventListener("click", () => fileInput.click());
    fileInput.addEventListener("change", (e) => {
      const file = e.target.files && e.target.files[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = (evt) => {
        try {
          const text = evt.target.result;
          const data = JSON.parse(text);
          setSessionJson(data);
          setOutput(`Сессия загружена из файла: ${file.name}`);
        } catch (err) {
          setOutput("Ошибка чтения файла сессии: " + err.message);
        }
      };
      reader.readAsText(file, "utf-8");
    });
  }

  const btnLoadSession = document.getElementById("btn-load-session");
  if (btnLoadSession) {
    btnLoadSession.addEventListener("click", async () => {
      const select = document.getElementById("select-sessions");
      const name = select?.value?.trim();
      if (!name) {
        setOutput("Выберите сессию из списка.");
        return;
      }
      try {
        await loadSessionByName(name);
        localStorage.setItem("lastSessionName", name);
        setOutput(`Сессия загружена: ${name}`);
      } catch (e) {
        setOutput("Ошибка загрузки сессии: " + e.message);
      }
    });
  }

  const btnNewSession = document.getElementById("btn-new-session");
  if (btnNewSession) {
    btnNewSession.addEventListener("click", () => {
      const now = new Date();
      const baseName = "Новая сессия";
      const fullName = `${baseName} ${buildSessionTimestamp(now)}`;

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
        registry_rows: [],
        settings: {},
      };
      try {
        localStorage.removeItem("lastSessionName");
      } catch (_) {}
      renderAllViews();
      setOutput("Создана новая пустая сессия.");
    });
  }

  const registryTable = document.getElementById("registry-table");
  if (registryTable) {
    registryTable.addEventListener("input", (e) => {
      const target = e.target;
      if (!target.classList.contains("reg-input")) return;
      const tr = target.closest("tr");
      const idx = Number.parseInt(tr?.dataset.index || "-1", 10);
      const field = target.dataset.field;
      const session = getSessionJson();
      if (!session || !Array.isArray(session.registry_rows) || !field || idx < 0) return;
      session.registry_rows[idx][field] = target.value;
      syncTextareaFromSession();
      renderRegistry();
    });

    registryTable.addEventListener("click", (e) => {
      const target = e.target;
      const tr = target.closest("tr");
      const idx = Number.parseInt(tr?.dataset.index || "-1", 10);
      const session = getSessionJson();
      if (!session || !Array.isArray(session.registry_rows) || idx < 0) return;
      const rows = session.registry_rows;
      if (target.classList.contains("btn-reg-up") && idx > 0) {
        [rows[idx - 1], rows[idx]] = [rows[idx], rows[idx - 1]];
      } else if (target.classList.contains("btn-reg-down") && idx < rows.length - 1) {
        [rows[idx], rows[idx + 1]] = [rows[idx + 1], rows[idx]];
      } else {
        return;
      }
      rows.forEach((r, i) => {
        r.number = i + 1;
        r.sheet = i + 1;
        const doc = (session.documents || []).find((d) => d.id === r.doc_id);
        if (doc) doc.order = i + 1;
      });
      syncAosrOrderByNumber(session);
      renderAllViews();
    });
  }

  // Автозагрузка: сначала последняя сохранённая сессия, иначе sample.
  loadTemplates();
  loadLastOrSampleSession();
});
