let currentSession = null;
let templatesCache = [];
let currentTemplateName = null;

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
    const session = getSessionJson();
    if (!session) {
      setOutput("Нет данных сессии для сохранения");
      return;
    }
    const nameInput = document.getElementById("input-session-name");
    const baseNameRaw = nameInput?.value?.trim() || session?.meta?.name || "session";

    const now = new Date();
    const dd = String(now.getDate()).padStart(2, "0");
    const mm = String(now.getMonth() + 1).padStart(2, "0");
    const yyyy = now.getFullYear();
    const hh = String(now.getHours()).padStart(2, "0");
    const min = String(now.getMinutes()).padStart(2, "0");
    const stamp = `${dd}.${mm}.${yyyy} ${hh}.${min}`; // День.месяц.год час.минута

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
        localStorage.setItem("lastSessionName", fullName);
      } catch (_) {}
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
  const session = getSessionJson();
  const tbody = document.querySelector("#aosr-table tbody");
  if (!tbody) return;
  tbody.innerHTML = "";
  if (!session) return;
  const docs = (session.documents || []).slice().sort((a, b) => (a.order || 0) - (b.order || 0));
  docs
    .filter((d) => (d.type || "").trim() === "АОСР")
    .forEach((d) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${d.order ?? ""}</td>
        <td>${d.id ?? ""}</td>
        <td>${d.title ?? ""}</td>
        <td>${d.start_date ?? ""}</td>
        <td>${d.end_date ?? ""}</td>
        <td>${d.manual_override ? "✓" : ""}</td>
      `;
      tbody.appendChild(tr);
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
        <button type="button" class="btn-build-meta" data-docx="${t.docx_name}">
          ${hasMeta ? "Пересоздать" : "Сгенерировать"} metadata
        </button>
      </td>
    `;
    tbody.appendChild(tr);
  });
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
    const fields = (data.metadata && data.metadata.fields) || {};
    const fieldKeys = Object.keys(fields || {});
    if (fieldKeys.length > 0) {
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

  const btnNewSession = document.getElementById("btn-new-session");
  if (btnNewSession) {
    btnNewSession.addEventListener("click", () => {
      const now = new Date();
      const dd = String(now.getDate()).padStart(2, "0");
      const mm = String(now.getMonth() + 1).padStart(2, "0");
      const yyyy = now.getFullYear();
      const hh = String(now.getHours()).padStart(2, "0");
      const min = String(now.getMinutes()).padStart(2, "0");
      const stamp = `${dd}.${mm}.${yyyy} ${hh}.${min}`;

      const baseName = "Новая_сессия";
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
      renderAllViews();
      setOutput("Создана новая пустая сессия.");
    });
  }

  // Автозагрузка: сначала последняя сохранённая сессия, иначе sample.
  loadLastOrSampleSession();
});

