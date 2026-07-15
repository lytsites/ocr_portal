<template>
  <div class="app-shell">
    <header v-if="!isAnalyticsRoute" class="topbar">
      <div class="topbar-inner">
        <div class="brand-wrap">
          <div class="brand-copy">
            <div class="brand-title">{{ siteBrandTitle }}</div>
            <div class="brand-sub">Панель чтения финансовых документов</div>
          </div>
        </div>
        <nav class="tabs">
          <div class="site-switch-wrap">
            <button class="btn site-switch-trigger" type="button" @click.stop="toggleSiteSwitch" :aria-expanded="siteSwitchOpen ? 'true' : 'false'">
              Другие формы
              <svg class="site-switch-arrow" :class="{ open: siteSwitchOpen }" viewBox="0 0 16 16" aria-hidden="true">
                <path d="M3 6.5L8 11L13 6.5" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" />
              </svg>
            </button>
            <div v-if="siteSwitchOpen" class="site-switch-pop" @click.stop>
              <div class="site-switch-title">Панели для других форм документов</div>
              <a v-for="link in siteLinks" :key="link.label" class="site-switch-link" :href="link.url">PDF/{{ link.label }}</a>
            </div>
          </div>
          <button class="btn primary" @click="openUpload">Загрузить</button>
          <button class="btn" :class="{ active: activeTab === 'dashboard' }" @click="activeTab = 'dashboard'">Главная</button>
          <button class="btn" :class="{ active: activeTab === 'documents' }" @click="activeTab = 'documents'">Реестр</button>
          <a class="btn" :class="{ active: isAnalyticsRoute }" :href="analyticsUrl">Аналитика</a>
        </nav>
      </div>
    </header>

    <AnalyticsView v-if="isAnalyticsRoute" />

    <main class="content" v-else-if="activeTab === 'dashboard'">
      <section class="hero card">
        <div class="hero-bg a"></div>
        <div class="hero-bg b"></div>
        <div>
          <h1>Панель чтения PDF</h1>
          <p>Загрузка, верификация и чтение платежных документов для профильных подразделений.</p>
          <div class="hero-actions">
            <button class="btn primary" style="min-width:240px" @click="openUpload">Загрузить документы</button>
            <button class="btn" @click="activeTab = 'documents'">Открыть реестр</button>
          </div>
        </div>
      </section>
    </main>

    <main class="content" v-else-if="activeTab === 'documents'">
      <section class="card">
        <h2 style="margin:0">Реестр загруженных документов</h2>
        <div class="table-wrap">
          <table class="table" id="docsTable">
            <thead>
              <tr>
                <th>ID</th>
                <th>Документ</th>
                <th>Форма</th>
                <th>Режим</th>
                <th>Статус</th>
                <th>Этап обработки</th>
                <th>Прогресс этапа</th>
                <th>Очередь</th>
                <th>Действия</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="documentsError"><td colspan="10" class="muted">Ошибка загрузки реестра: {{ documentsError }}</td></tr>
              <tr v-else-if="documents.length === 0"><td colspan="10" class="muted">Документы пока не загружены.</td></tr>
              <tr v-for="d in documents" :key="d.id">
                <td><code>{{ d.id }}</code></td>
                <td>
                  {{ d.name }}
                  <div v-if="d.duplicate_of" class="muted">дубликат документа: {{ d.duplicate_of }}</div>
                </td>
                <td><code>{{ formTitle(d.form_type) }}</code></td>
                <td><span class="muted">{{ uploadModeTitle(d.upload_mode) }}</span></td>
                <td><span class="pill" :class="statusClass(d.status)">{{ statusRu(d.status) }}</span></td>
                <td>{{ d.stage || '' }}</td>
                <td>
                  <div class="muted">{{ progressStageLabel(d.stage) }}</div>
                  <div class="progress"><span :style="{ width: progressPercent(d) + '%' }"></span></div>
                  <div class="muted">{{ processed(d) }} / {{ total(d) }} ({{ progressPercent(d) }}%)</div>
                </td>
                <td>{{ queueText(d.queue) }}</td>
                <td style="display:flex;gap:8px;flex-wrap:wrap">
                  <button class="btn" @click="openDocument(d.id)">Открыть</button>
                  <button
                    v-if="documentDeleteEnabled"
                    class="btn danger"
                    :disabled="isDeleteLocked(d)"
                    @click="confirmDeleteDocument(d)"
                  >
                    Удалить
                  </button>
                </td>
              </tr>
              <tr v-if="pipelineMetrics.enabled && pipelineMetrics.summary_text">
                <td colspan="10" class="muted">Итог прогона очереди: {{ pipelineMetrics.summary_text }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </main>

    <main class="content" v-else-if="activeTab === 'document'">
      <section class="card">
        <h2 style="margin:0">Карточка документа</h2>
        <div style="margin-top:10px">
          <button class="btn" :disabled="!selectedDocumentId" @click="openFormPreview">Открыть форму</button>
        </div>
        <div v-if="isDocumentHeaderReady" style="margin-top:12px">
          <div v-for="(line, idx) in documentMetaLines" :key="`meta_${idx}`" class="muted" :style="{ marginTop: idx === 0 ? '0' : '6px' }">
            {{ line }}
          </div>
        </div>
        <div v-else class="muted" style="margin-top:12px">
          Данные документа загружаются. Шапка появится после полного чтения.
        </div>
        <div v-if="isDocumentHeaderReady && isForm219 && hasForm219Groups" style="margin-top:10px">
          <button class="btn" @click="toggleAllForm219Groups">{{ allForm219GroupsCollapsed ? "Развернуть все" : "Свернуть все" }}</button>
        </div>
        <div v-if="isDocumentHeaderReady && isForm420 && hasForm420CollapsibleRows" style="margin-top:10px">
          <button class="btn" @click="toggleAllForm420Rows">{{ allForm420Collapsed ? "Развернуть все" : "Свернуть все" }}</button>
        </div>
        <div class="table-wrap">
          <table class="table" id="cellsTable">
            <thead>
              <tr>
                <th v-for="(h, idx) in tableHeaders" :key="`h_${idx}`">{{ h }}</th>
              </tr>
            </thead>
            <tbody>
            <tr v-if="documentRows.length === 0">
              <td :colspan="tableHeaders.length" class="muted">Строки таблицы пока отсутствуют.</td>
            </tr>
            <tr
              v-for="entry in pagedVisibleDocumentRows"
              :key="entry.sourceIndex"
              :class="{
                'group-header': isForm219GroupHeader(entry.sourceIndex),
                'tree-header': isForm420RowCollapsible(entry.sourceIndex),
                collapsed: isForm219GroupCollapsed(entry.sourceIndex),
                'tree-collapsed': isForm420RowCollapsed(entry.sourceIndex),
                'supplementary-row': isForm243SupplementaryRow(entry.sourceIndex),
                'tail-summary-row': isForm243TailSummaryRow(entry.sourceIndex),
              }"
              @click="onDocumentRowClick(entry.sourceIndex)"
            >
              <td
                v-for="cell in rowCells(entry)"
                :key="`r_${entry.sourceIndex}_c_${cell.col}`"
                :colspan="cell.colspan"
                :class="{
                  'tail-cell-right': !!cell.alignRight,
                  'form219-first-col': isForm219 && cell.col === 0 && !isForm219GroupHeader(entry.sourceIndex),
                  'form420-last-first-col': isForm420 && cell.col === 0 && isForm420LastRow(entry.sourceIndex),
                  'form552-total-cell': !!cell.form552Total,
                }"
                :style="cellStyle(entry.sourceIndex, cell.col)"
              >
                <template v-if="cell.col === 0 && isRowWithToggle(entry.sourceIndex)">
                  <span class="row-toggle">{{ rowToggleSymbol(entry.sourceIndex) }}</span>
                  {{ cell.text || '' }}
                </template>
                <template v-else>
                  <template v-if="isForm243SupplementaryRow(entry.sourceIndex) && cell.col === 4">
                    <span class="supplementary-label">Расшифровка (не влияет на итог): </span>{{ cell.text || '' }}
                  </template>
                  <template v-else>
                    {{ cell.text || '' }}
                  </template>
                </template>
              </td>
            </tr>
            </tbody>
          </table>
        </div>
        <div v-if="visibleDocumentRows.length > documentPageSize" class="doc-pagination">
          <button class="btn" :disabled="currentDocumentPage <= 1" @click="currentDocumentPage -= 1">Назад</button>
          <div class="muted">Страница {{ currentDocumentPage }} / {{ documentTotalPages }} · строк: {{ visibleDocumentRows.length }}</div>
          <button class="btn" :disabled="currentDocumentPage >= documentTotalPages" @click="currentDocumentPage += 1">Вперед</button>
        </div>
      </section>
    </main>

    <main class="content" v-else />

    <div class="modal" :class="{ open: formPreviewOpen }" @click="onFormPreviewBackdrop">
      <div class="modal-inner">
        <div style="display:flex;justify-content:space-between;align-items:center;gap:10px">
          <strong>Исходная форма PDF</strong>
          <button class="btn" @click="closeFormPreview">Закрыть</button>
        </div>
        <div style="margin-top:10px">
          <input
            v-model="formPreviewQuery"
            type="text"
            placeholder="Поиск по PDF"
            style="width:100%;padding:10px 12px;border:1px solid var(--line);border-radius:10px"
          />
        </div>
        <div class="preview" style="margin-top:10px; min-height: calc(100vh - 180px);">
          <PdfSearchViewer v-if="formPreviewSrc" :src="formPreviewSrc" :query="formPreviewQuery" height="calc(100vh - 180px)" />
          <div v-else class="muted" style="padding:14px">Документ не выбран.</div>
        </div>
      </div>
    </div>

    <div class="modal" :class="{ open: uploadOpen }" @click="onBackdrop">
      <div class="modal-inner">
        <div style="display:flex;justify-content:space-between;align-items:center;gap:10px">
          <strong>Загрузка финансовых документов</strong>
          <button class="btn" @click="closeUpload">Закрыть</button>
        </div>

        <div class="grid" style="margin-top:10px">
          <section class="card">
            <div class="muted">Форма: <code>{{ formLabel }}</code></div>
            <div style="margin-top:10px">
              <span class="muted">Выбор формы отключен: этот фронт работает только с формой <code>{{ formLabel }}</code>.</span>
            </div>
            <div style="margin-top:16px">
              <strong>Режим загрузки</strong>
              <div class="muted" style="margin-top:6px">Стандартный путь читает PDF напрямую. OCR-режим нужен для сканов: он уже заводит отдельный маршрут пайплайна и готовит страницы как изображения.</div>
              <div style="margin-top:10px;display:grid;gap:10px">
                <label
                  v-for="mode in uploadModes"
                  :key="mode.id"
                  class="card"
                  :style="{
                    cursor: uploadSubmitLocked ? 'default' : 'pointer',
                    border: selectedUploadMode === mode.id ? '1px solid var(--accent)' : '1px solid var(--line)',
                    background: selectedUploadMode === mode.id ? 'rgba(31,160,143,0.08)' : 'var(--panel)',
                    padding: '12px 14px'
                  }"
                >
                  <input
                    v-model="selectedUploadMode"
                    type="radio"
                    name="upload_mode"
                    :value="mode.id"
                    :disabled="uploadSubmitLocked"
                    style="margin-right:8px"
                  />
                  <strong>{{ mode.title }}</strong>
                  <div class="muted" style="margin-top:4px">{{ mode.description }}</div>
                </label>
              </div>
            </div>
            <div
              class="dropzone"
              :class="{ dragover: uploadDragover, disabled: uploadSubmitLocked }"
              style="margin-top:10px"
              @click="triggerFileInput"
              @dragover.prevent="onDragOver"
              @dragleave="onDragLeave"
              @drop.prevent="onDrop"
            >
              {{ uploadSubmitLocked ? "Загрузка выполняется..." : "Перетащите PDF в эту область или нажмите для выбора" }}
              <input ref="fileInputRef" type="file" accept="application/pdf" multiple hidden @change="onFileInputChange" />
            </div>

            <ul class="file-list">
              <li v-if="uploadFiles.length === 0" class="muted">Документы еще не выбраны</li>
              <li
                v-for="f in uploadFiles"
                :key="f.id"
                :class="{ active: selectedUploadId === f.id }"
                @click="selectedUploadId = f.id"
              >
                {{ f.file.name }}
              </li>
            </ul>

            <div class="status" :class="{ ok: uploadStatus && !uploadStatusError, error: uploadStatus && uploadStatusError }">{{ uploadStatus }}</div>
            <div style="margin-top:8px">
              <button class="btn primary" :disabled="uploadSubmitLocked" @click="sendUploads">Запустить обработку</button>
            </div>
          </section>

          <section class="card">
            <strong>Предпросмотр документа</strong>
            <div style="margin-top:10px">
              <input
                v-model="uploadPreviewQuery"
                type="text"
                placeholder="Поиск по PDF"
                style="width:100%;padding:10px 12px;border:1px solid var(--line);border-radius:10px"
              />
            </div>
            <div class="preview" style="margin-top:10px">
              <div v-if="!selectedUpload" class="muted" style="padding:14px">Выберите документ в списке слева для просмотра.</div>
              <PdfSearchViewer v-else :src="selectedUpload.url" :query="uploadPreviewQuery" height="360px" />
            </div>
          </section>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import AnalyticsView from "./components/AnalyticsView.vue";
import PdfSearchViewer from "./components/PdfSearchViewer.vue";
import { buildAnalyticsPath, buildFormPath, listFormProfiles, resolveRoute } from "./formProfiles";

const DEFAULT_UPLOAD_MODE = "pdf_text";
const DEFAULT_UPLOAD_MODES = [
  { id: "pdf_text", title: "Обычный PDF", description: "Чтение напрямую из PDF через текстовый слой и табличную структуру." },
  { id: "pdf_ocr", title: "PDF -> изображения -> OCR", description: "Подходит для сканов. Пока готовит OCR-контур и растровые страницы для следующего шага." },
];

function resolveApiBase() {
  const host = String(window.location.hostname || "").toLowerCase();
  if (host.endsWith(".e-qoldau.asia")) return "https://api.e-qoldau.asia";
  return String(import.meta.env.VITE_API_BASE || "https://api.e-qoldau.asia").replace(/\/+$/, "");
}

const API_BASE = resolveApiBase();
const ROUTE = resolveRoute();
const PROFILE = ROUTE.profile;
const FORM_ID = PROFILE.formId;
const FORM_LABEL = PROFILE.formLabel;
const SITE_BRAND_TITLE = PROFILE.brandTitle;
const ANALYTICS_URL = buildAnalyticsPath();
const SITE_LINKS = listFormProfiles().map((profile) => ({ label: profile.formLabel, url: buildFormPath(profile.slug) }));

const activeTab = ref("dashboard");
const siteSwitchOpen = ref(false);

const uploadOpen = ref(false);
const formPreviewOpen = ref(false);
const uploadPreviewQuery = ref("");
const formPreviewQuery = ref("");
const uploadDragover = ref(false);
const uploadSubmitLocked = ref(false);
const uploadFiles = ref([]);
const selectedUploadId = ref("");
const selectedUploadMode = ref(DEFAULT_UPLOAD_MODE);
const uploadModes = ref(DEFAULT_UPLOAD_MODES);
const uploadStatus = ref("");
const uploadStatusError = ref(false);
const fileInputRef = ref(null);
const formsCatalog = ref([{ id: FORM_ID, title: FORM_LABEL }]);

const documents = ref([]);
const documentsError = ref("");
const pipelineMetrics = ref({ enabled: false, summary_text: "" });
const appConfig = ref({ document_delete_enabled: false });
const selectedDocumentId = ref("");
const selectedDocument = ref(null);
const selectedDocumentTable = ref({ ready: false, headers: [], rows: [], row_indent_levels: [] });
const documentError = ref("");
const collapsed219Groups = ref(new Set());
const collapsed420Rows = ref(new Set());
const documentPageSize = 20;
const currentDocumentPage = ref(1);

let docsTimer = null;
let docTimer = null;
const formLabel = FORM_LABEL;
const siteBrandTitle = SITE_BRAND_TITLE;
const analyticsUrl = ANALYTICS_URL;
const currentFormPath = buildFormPath(PROFILE.slug);
const isAnalyticsRoute = ROUTE.type === "analytics";
const siteLinks = computed(() => (isAnalyticsRoute ? SITE_LINKS : SITE_LINKS.filter((x) => x.label !== FORM_LABEL)));
const documentDeleteEnabled = computed(() => !!appConfig.value.document_delete_enabled);

function makeId() {
  return `${Date.now()}_${Math.random()}`;
}

function makeEmptyDocumentTable() {
  return { ready: false, headers: [], rows: [], row_indent_levels: [] };
}

function toggleSiteSwitch() {
  siteSwitchOpen.value = !siteSwitchOpen.value;
}

function onDocumentClick() {
  siteSwitchOpen.value = false;
}

function statusRu(status) {
  const s = String(status || "").toLowerCase();
  if (s === "queued") return "в очереди";
  if (s === "processing") return "в обработке";
  if (s === "done") return "готов";
  if (s === "error") return "ошибка";
  if (s === "duplicate") return "дубликат";
  return s || "-";
}

function statusClass(status) {
  const s = String(status || "").toLowerCase();
  return ["queued", "processing", "done", "error", "duplicate"].includes(s) ? s : "queued";
}

function processed(d) {
  return Number(d?.processing?.progress?.processed || 0);
}

function total(d) {
  return Number(d?.processing?.progress?.total || 0);
}

function progressPercent(d) {
  return Number(d?.processing?.progress?.percent || 0);
}

function progressStageLabel(stage) {
  const s = String(stage || "").toLowerCase();
  if (s.startsWith("reading_pages")) return "Чтение страниц";
  if (s.startsWith("syncing_facts_cache_msb")) return "После чтения: кэш МСБ";
  if (s.startsWith("syncing_facts_cache_oked")) return "После чтения: кэш ОКЭД";
  if (s.startsWith("syncing_facts_cache")) return "После чтения: подготовка";
  if (s.startsWith("syncing_facts_rows")) return "После чтения: запись результатов";
  if (s === "completed") return "Готово";
  if (s === "duplicate_detected") return "Дубликат";
  return "Обработка";
}

function queueText(queue) {
  if (!queue) return "-";
  if (queue.state === "queued") return `позиция ${queue.position}`;
  if (queue.state === "processing") return "обрабатывается";
  return "-";
}

function formTitle(id) {
  const key = String(id || "");
  const found = formsCatalog.value.find((x) => String(x.id) === key);
  return found?.title || key || "-";
}

function uploadModeTitle(id) {
  const key = String(id || DEFAULT_UPLOAD_MODE);
  const found = uploadModes.value.find((x) => String(x.id) === key);
  return found?.title || key;
}

function parseAmount(value) {
  const raw = String(value || "").replace(/\s+/g, "");
  if (!raw) return 0;
  if (/^-?\d{1,3}(,\d{3})+(\.\d+)?$/.test(raw)) return Number.parseFloat(raw.replace(/,/g, "")) || 0;
  if (/^-?\d{1,3}(\.\d{3})+(,\d+)?$/.test(raw)) return Number.parseFloat(raw.replace(/\./g, "").replace(",", ".")) || 0;
  const lastComma = raw.lastIndexOf(",");
  const lastDot = raw.lastIndexOf(".");
  if (lastComma !== -1 && lastDot !== -1) {
    const decimalSep = lastComma > lastDot ? "," : ".";
    const normalized = decimalSep === "," ? raw.replace(/\./g, "").replace(",", ".") : raw.replace(/,/g, "");
    return Number.parseFloat(normalized) || 0;
  }
  if (lastComma !== -1) {
    const parts = raw.split(",");
    if (parts.length === 2 && parts[1].length === 2) return Number.parseFloat(raw.replace(",", ".")) || 0;
    return Number.parseFloat(raw.replace(/,/g, "")) || 0;
  }
  return Number.parseFloat(raw) || 0;
}

function formatAmount(value) {
  return new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value || 0);
}

const selectedUpload = computed(() => uploadFiles.value.find((x) => x.id === selectedUploadId.value) || uploadFiles.value[0] || null);
const formPreviewSrc = computed(() =>
  selectedDocumentId.value ? `${API_BASE}/api/documents/${encodeURIComponent(selectedDocumentId.value)}/preview` : ""
);
const documentRows = computed(() => selectedDocumentTable.value?.rows || []);
const rowIndentLevels = computed(() => selectedDocumentTable.value?.row_indent_levels || []);
const tableHeaders = computed(() => {
  const fromApi = selectedDocumentTable.value?.headers;
  if (Array.isArray(fromApi) && fromApi.length) return fromApi;
  return [];
});
const isForm552 = computed(() => FORM_ID === "form_5_52");
const isForm243 = computed(() => FORM_ID === "form_2_43");
const isForm219 = computed(() => FORM_ID === "form_2_19");
const isForm420 = computed(() => FORM_ID === "form_4_20");
const form219ParentGroupByRow = computed(() => {
  const rows = Array.isArray(documentRows.value) ? documentRows.value : [];
  const parent = new Array(rows.length).fill(-1);
  if (!isForm219.value) return parent;
  let currentGroupStart = -1;
  for (let i = 0; i < rows.length; i += 1) {
    const row = rows[i] || [];
    const col1 = String(row[0] || "").trim();
    if (col1) {
      currentGroupStart = i;
      parent[i] = -1;
      continue;
    }
    parent[i] = currentGroupStart;
  }
  return parent;
});
const form219GroupStarts = computed(() => {
  if (!isForm219.value) return [];
  const rows = Array.isArray(documentRows.value) ? documentRows.value : [];
  const parent = form219ParentGroupByRow.value || [];
  const starts = [];
  for (let i = 0; i < rows.length; i += 1) {
    const row = rows[i] || [];
    if (!String(row[0] || "").trim()) continue;
    if (i + 1 < rows.length && parent[i + 1] === i) starts.push(i);
  }
  return starts;
});
const hasForm219Groups = computed(() => Array.isArray(form219GroupStarts.value) && form219GroupStarts.value.length > 0);
const allForm219GroupsCollapsed = computed(() => {
  const starts = form219GroupStarts.value;
  if (!starts.length) return false;
  return starts.every((i) => collapsed219Groups.value.has(i));
});
const form420Levels = computed(() => {
  const rows = Array.isArray(documentRows.value) ? documentRows.value : [];
  const src = Array.isArray(rowIndentLevels.value) ? rowIndentLevels.value : [];
  return rows.map((_, i) => Math.max(0, Number(src[i] || 0)));
});
const form420CollapsibleRows = computed(() => {
  if (!isForm420.value) return new Set();
  const levels = form420Levels.value;
  const out = new Set();
  for (let i = 0; i < levels.length; i += 1) {
    const lvl = levels[i];
    if (lvl >= 3) continue;
    for (let j = i + 1; j < levels.length; j += 1) {
      const lj = levels[j];
      if (lj <= lvl) break;
      if (lj > lvl) {
        out.add(i);
        break;
      }
    }
  }
  return out;
});
const hasForm420CollapsibleRows = computed(() => form420CollapsibleRows.value.size > 0);
const allForm420Collapsed = computed(() => {
  const nodes = form420CollapsibleRows.value;
  if (!nodes.size) return false;
  for (const idx of nodes) {
    if (!collapsed420Rows.value.has(idx)) return false;
  }
  return true;
});
const isDocumentHeaderReady = computed(() => {
  const status = String(selectedDocument.value?.status || "").toLowerCase();
  return status === "done" && !!selectedDocumentTable.value?.ready;
});
const visibleDocumentRows = computed(() => {
  const rows = Array.isArray(documentRows.value) ? documentRows.value : [];
  if (!isForm219.value && !isForm420.value) return rows.map((row, sourceIndex) => ({ row, sourceIndex }));

  if (isForm219.value) {
    const parent = form219ParentGroupByRow.value || [];
    const out = [];
    for (let i = 0; i < rows.length; i += 1) {
      const row = rows[i] || [];
      const parentGroup = parent[i];
      if (parentGroup >= 0 && collapsed219Groups.value.has(parentGroup)) {
        continue;
      }
      out.push({ row, sourceIndex: i });
    }
    return out;
  }

  const levels = form420Levels.value;
  const hiddenBy = [];
  const out = [];
  for (let i = 0; i < rows.length; i += 1) {
    const row = rows[i] || [];
    const lvl = levels[i] ?? 0;
    while (hiddenBy.length && lvl <= hiddenBy[hiddenBy.length - 1]) {
      hiddenBy.pop();
    }
    if (hiddenBy.length) {
      continue;
    }
    out.push({ row, sourceIndex: i });
    if (collapsed420Rows.value.has(i)) {
      hiddenBy.push(lvl);
    }
  }
  return out;
});
const documentTotalPages = computed(() => {
  const totalRows = visibleDocumentRows.value.length;
  if (totalRows <= 0) return 1;
  return Math.ceil(totalRows / documentPageSize);
});
const pagedVisibleDocumentRows = computed(() => {
  const start = (currentDocumentPage.value - 1) * documentPageSize;
  return visibleDocumentRows.value.slice(start, start + documentPageSize);
});
const form243TailSummaryIndexes = computed(() => {
  if (!isForm243.value) return [];
  const rows = Array.isArray(documentRows.value) ? documentRows.value : [];
  const nonEmpty = [];
  for (let i = 0; i < rows.length; i += 1) {
    const row = rows[i] || [];
    if (row.some((x) => String(x || "").trim())) nonEmpty.push(i);
  }
  if (nonEmpty.length < 4) return [];
  return nonEmpty.slice(-4);
});
const documentMetaLines = computed(() => {
  if (documentError.value) return [`Ошибка: ${documentError.value}`];
  if (!selectedDocument.value) return ["Загрузка данных документа..."];

  const form = FORM_ID;
  const meta = selectedDocumentTable.value?.meta || {};
  const lines = [];

  const add = (label, key) => {
    const v = String(meta?.[key] || "").trim();
    if (v) lines.push(`${label}: ${v}`);
  };

  if (form === "form_2_19") {
    add("Регион", "region");
    add("Дата", "date");
  } else if (form === "form_2_43") {
    add("Регион", "region");
    add("Период", "period");
    add("Код дохода", "income_code");
  } else if (form === "form_4_20") {
    add("Вид бюджета", "budget_type");
    add("Месторасположение", "location");
    add("Источник финансирования", "funding_source");
    add("Администратор Бюджетных программ", "admin_program");
    add("Наименование государственного учреждения", "institution_name");
    add("Дата", "date");
  } else if (form === "form_5_52") {
    add("Вид бюджета", "budget_type");
    add("Регион", "region");
    add("Специфика", "specific");
    add("Источник финансирования", "funding_source");
    add("Дата", "date");
  }

  if (!lines.length) {
    const status = String(selectedDocument.value?.status || "").toLowerCase();
    const stage = String(selectedDocument.value?.stage || "").toLowerCase();
    const ready = status === "done" || stage === "completed";
    lines.push(`Документ: ${selectedDocument.value?.name || "-"}`);
    lines.push(`Форма: ${formTitle(selectedDocument.value?.form_type)}`);
    lines.push(`Статус: ${statusRu(selectedDocument.value?.status)}${ready ? "" : ` (${selectedDocument.value?.stage || "-"})`}`);
  }
  return lines;
});

function cellStyle(rowIndex, colIndex) {
  if (colIndex !== 0) return {};
  const lvl = Number(rowIndentLevels.value?.[rowIndex] || 0);
  const px = Math.max(0, lvl) * 18;
  return px > 0 ? { paddingLeft: `${px}px` } : {};
}

function isAmountLike(value) {
  const s = String(value || "").trim().replace(/\s+/g, "");
  if (!s) return false;
  if (/^-?\d+(?:[.,]\d+)?$/.test(s)) return true;
  if (/^-?\d{1,3}(?:[.,]\d{3})+(?:[.,]\d+)?$/.test(s)) return true;
  return false;
}

function isForm243MergedRow(row) {
  if (!isForm243.value) return false;
  const r = Array.isArray(row) ? row : [];
  const c0 = String(r[0] || "").trim();
  const c1 = String(r[1] || "").trim();
  const c2 = String(r[2] || "").trim();
  const c3 = String(r[3] || "").trim();
  const c4 = String(r[4] || "").trim();
  const c5 = String(r[5] || "").trim();
  const c6 = String(r[6] || "").trim();
  const c7 = String(r[7] || "").trim();
  if (c0 || c1 || c2) return false;
  if (!c3 || !c4) return false;
  const amountIn7 = !!c7;
  const amountIn5 = isAmountLike(c5) && !c7;
  return !c6 && (amountIn7 || amountIn5);
}

function isForm552AbpTotalRowText(value) {
  const s = String(value || "")
    .toLowerCase()
    .replace(/\s+/g, " ")
    .trim();
  return s.startsWith("итого по абп");
}

function isForm552LastDataRow(sourceIndex) {
  if (!isForm552.value) return false;
  const rows = Array.isArray(documentRows.value) ? documentRows.value : [];
  let last = -1;
  for (let i = 0; i < rows.length; i += 1) {
    const row = rows[i] || [];
    if (row.some((x) => String(x || "").trim())) last = i;
  }
  return sourceIndex === last;
}

function rowCells(entry) {
  const row = Array.isArray(entry?.row) ? entry.row : [];
  const cols = tableHeaders.value.length;
  const cells = [];
  const srcIdx = Number(entry?.sourceIndex ?? -1);
  const raw = (v) => String(v || "").trim();
  const pickFirst = (start, end) => {
    for (let i = start; i <= end; i += 1) {
      const t = raw(row[i]);
      if (t) return t;
    }
    return "";
  };

  if (isForm243.value && cols >= 8) {
    const tail = form243TailSummaryIndexes.value;
    const tailPos = tail.indexOf(srcIdx);
    if (tailPos !== -1) {
      // Last 4 summary lines in 2-43 with custom colspan layout.
      if (tailPos === 2) {
        // 3rd of 4: col1 spans 4, col5 spans 4.
        const left = pickFirst(0, 3);
        const right = pickFirst(4, 7);
        cells.push({ col: 0, text: left, colspan: 4, alignRight: true });
        cells.push({ col: 4, text: right, colspan: 4, alignRight: true });
        return cells;
      }
      // 1st, 2nd, 4th of 4: col1 spans 3, col4 as-is, col5 spans 4.
      const left = pickFirst(0, 2);
      const mid = raw(row[3] || "");
      const right = pickFirst(4, 7);
      cells.push({ col: 0, text: left, colspan: 3, alignRight: true });
      cells.push({ col: 3, text: mid, colspan: 1, alignRight: true });
      cells.push({ col: 4, text: right, colspan: 4, alignRight: true });
      return cells;
    }
  }

  if (isForm552.value && cols >= 5) {
    const c1 = raw(row[0]);
    if (isForm552AbpTotalRowText(c1) || isForm552LastDataRow(srcIdx)) {
      const totalText = [row[0], row[1], row[2]]
        .map((x) => String(x || "").replace(/\s+/g, " ").trim())
        .find((x) => x) || "";
      cells.push({ col: 0, text: totalText, colspan: 3, alignRight: true, form552Total: true });
      cells.push({ col: 3, text: row[3] || "", colspan: 1, alignRight: false, form552Total: false });
      cells.push({ col: 4, text: row[4] || "", colspan: 1, alignRight: false, form552Total: false });
      return cells;
    }
  }

  if (!isForm243MergedRow(row)) {
    for (let c = 0; c < cols; c += 1) {
      cells.push({ col: c, text: row[c] || "", colspan: 1, alignRight: false });
    }
    return cells;
  }

  const amountFrom5 = isAmountLike(row[5]) && !String(row[7] || "").trim();
  const mergedText = amountFrom5
    ? [row[4] || "", row[6] || ""].filter((x) => String(x).trim()).join(" ")
    : [row[4] || "", row[5] || "", row[6] || ""].filter((x) => String(x).trim()).join(" ");

  for (let c = 0; c < cols; c += 1) {
    if (c === 4) {
      cells.push({ col: 4, text: mergedText, colspan: 3, alignRight: false });
      c = 6;
      continue;
    }
    if (c === 7 && amountFrom5) {
      cells.push({ col: 7, text: row[5] || "", colspan: 1, alignRight: false });
      continue;
    }
    cells.push({ col: c, text: row[c] || "", colspan: 1, alignRight: false });
  }
  return cells;
}

function isForm243SupplementaryRow(sourceIndex) {
  if (!isForm243.value) return false;
  const row = documentRows.value?.[sourceIndex] || [];
  return isForm243MergedRow(row);
}

function isForm243TailSummaryRow(sourceIndex) {
  if (!isForm243.value) return false;
  return form243TailSummaryIndexes.value.includes(sourceIndex);
}

function isForm219GroupHeader(sourceIndex) {
  if (!isForm219.value) return false;
  const rows = Array.isArray(documentRows.value) ? documentRows.value : [];
  const row = rows[sourceIndex] || [];
  if (!String(row[0] || "").trim()) return false;
  return form219GroupStarts.value.includes(sourceIndex);
}

function isForm219GroupCollapsed(sourceIndex) {
  return isForm219GroupHeader(sourceIndex) && collapsed219Groups.value.has(sourceIndex);
}

function onDocumentRowClick(sourceIndex) {
  if (isForm219.value) {
    if (!isForm219GroupHeader(sourceIndex)) return;
    const next = new Set(collapsed219Groups.value);
    if (next.has(sourceIndex)) next.delete(sourceIndex);
    else next.add(sourceIndex);
    collapsed219Groups.value = next;
    return;
  }
  if (isForm420.value) {
    if (!form420CollapsibleRows.value.has(sourceIndex)) return;
    const next = new Set(collapsed420Rows.value);
    if (next.has(sourceIndex)) next.delete(sourceIndex);
    else next.add(sourceIndex);
    collapsed420Rows.value = next;
  }
}

function isForm420RowCollapsible(sourceIndex) {
  return isForm420.value && form420CollapsibleRows.value.has(sourceIndex);
}

function isForm420RowCollapsed(sourceIndex) {
  return isForm420RowCollapsible(sourceIndex) && collapsed420Rows.value.has(sourceIndex);
}

function rowToggleSymbol(sourceIndex) {
  if (isForm219GroupHeader(sourceIndex)) {
    return isForm219GroupCollapsed(sourceIndex) ? "▸" : "▾";
  }
  if (isForm420RowCollapsible(sourceIndex)) {
    return isForm420RowCollapsed(sourceIndex) ? "▸" : "▾";
  }
  return "";
}

function isRowWithToggle(sourceIndex) {
  return isForm219GroupHeader(sourceIndex) || isForm420RowCollapsible(sourceIndex);
}

function isForm420LastRow(sourceIndex) {
  if (!isForm420.value) return false;
  const rows = Array.isArray(documentRows.value) ? documentRows.value : [];
  return sourceIndex === (rows.length - 1);
}

function toggleAllForm219Groups() {
  const starts = form219GroupStarts.value;
  if (!starts.length) return;
  if (allForm219GroupsCollapsed.value) {
    collapsed219Groups.value = new Set();
    return;
  }
  collapsed219Groups.value = new Set(starts);
}

function toggleAllForm420Rows() {
  const nodes = form420CollapsibleRows.value;
  if (!nodes.size) return;
  if (allForm420Collapsed.value) {
    collapsed420Rows.value = new Set();
    return;
  }
  collapsed420Rows.value = new Set(nodes);
}

async function apiGet(path) {
  const res = await fetch(`${API_BASE}${path}`);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || "Request failed");
  return data;
}

async function apiPostForm(path, formData) {
  const res = await fetch(`${API_BASE}${path}`, { method: "POST", body: formData });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || "Request failed");
  return data;
}

async function apiDelete(path) {
  const res = await fetch(`${API_BASE}${path}`, { method: "DELETE" });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || "Request failed");
  return data;
}

function resetUpload() {
  uploadFiles.value.forEach((f) => URL.revokeObjectURL(f.url));
  uploadFiles.value = [];
  selectedUploadId.value = "";
  selectedUploadMode.value = DEFAULT_UPLOAD_MODE;
  uploadPreviewQuery.value = "";
  uploadStatus.value = "";
  uploadStatusError.value = false;
  uploadDragover.value = false;
  uploadSubmitLocked.value = false;
}

function openUpload() {
  uploadOpen.value = true;
}

function closeUpload() {
  uploadOpen.value = false;
  resetUpload();
}

function onBackdrop(e) {
  if (e.target.classList.contains("modal")) closeUpload();
}

function openFormPreview() {
  if (!selectedDocumentId.value) return;
  formPreviewOpen.value = true;
}

function closeFormPreview() {
  formPreviewOpen.value = false;
  formPreviewQuery.value = "";
}

function onFormPreviewBackdrop(e) {
  if (e.target.classList.contains("modal")) closeFormPreview();
}

function triggerFileInput() {
  if (uploadSubmitLocked.value) return;
  fileInputRef.value?.click();
}

function addFiles(fileList) {
  const next = [];
  for (const f of Array.from(fileList || [])) {
    if (!String(f.name || "").toLowerCase().endsWith(".pdf")) continue;
    next.push({ id: makeId(), file: f, url: URL.createObjectURL(f) });
  }
  if (!next.length) return;
  uploadFiles.value = [...uploadFiles.value, ...next];
  if (!selectedUploadId.value) selectedUploadId.value = uploadFiles.value[0].id;
}

function onDrop(e) {
  if (uploadSubmitLocked.value) return;
  uploadDragover.value = false;
  addFiles(e.dataTransfer?.files);
}

function onDragOver() {
  if (uploadSubmitLocked.value) return;
  uploadDragover.value = true;
}

function onDragLeave() {
  uploadDragover.value = false;
}

function onFileInputChange(e) {
  if (uploadSubmitLocked.value) return;
  addFiles(e.target.files);
  e.target.value = "";
}

async function sendUploads() {
  if (!uploadFiles.value.length) {
    uploadStatus.value = "Добавьте минимум один PDF-документ";
    uploadStatusError.value = true;
    return;
  }
  uploadSubmitLocked.value = true;
  uploadStatus.value = "Документы отправляются в систему обработки...";
  uploadStatusError.value = false;

  const total = uploadFiles.value.length;
  const dpi = "300";
  const uploadMode = String(selectedUploadMode.value || DEFAULT_UPLOAD_MODE);
  const items = [];
  let failed = 0;

  try {
    for (let i = 0; i < total; i += 1) {
      const x = uploadFiles.value[i];
      uploadStatus.value = `Загрузка ${i + 1}/${total}: ${x.file.name}`;
      const fd = new FormData();
      fd.append("files", x.file);
      fd.append("dpi", dpi);
      fd.append("form_type", FORM_ID);
      fd.append("upload_mode", uploadMode);
      try {
        const res = await apiPostForm("/api/uploads", fd);
        const got = res.items || [];
        items.push(...got);
      } catch (_e) {
        failed += 1;
      }
    }

    const duplicates = items.filter((x) => x.status === "duplicate");
    const queued = items.filter((x) => x.status !== "duplicate");
    uploadStatus.value =
      `Принято документов: ${items.length} из ${total}. В очереди на чтение: ${queued.length}.` +
      (duplicates.length ? ` Дубликатов: ${duplicates.length}.` : "") +
      (failed ? ` Ошибок отправки: ${failed}.` : "");
    uploadStatusError.value = failed > 0 && items.length === 0;
    setTimeout(() => {
      closeUpload();
      activeTab.value = "documents";
      loadDocuments();
    }, 600);
  } catch (e) {
    uploadStatus.value = e.message || "Ошибка при отправке документов";
    uploadStatusError.value = true;
  }
}

async function loadDocuments() {
  const [docsRes, metricsRes] = await Promise.allSettled([
    apiGet("/api/documents"),
    apiGet("/api/metrics/pipeline"),
  ]);

  if (docsRes.status === "fulfilled") {
    const allItems = Array.isArray(docsRes.value.items) ? docsRes.value.items : [];
    documents.value = allItems.filter((x) => String(x?.form_type || "") === FORM_ID);
    documentsError.value = "";
  } else {
    documentsError.value = docsRes.reason?.message || "Ошибка загрузки реестра";
  }

  if (metricsRes.status === "fulfilled") {
    pipelineMetrics.value = {
      enabled: !!metricsRes.value?.enabled,
      summary_text: String(metricsRes.value?.summary_text || ""),
    };
  }
}

async function loadUploadModes() {
  try {
    const out = await apiGet("/api/upload-modes");
    const items = Array.isArray(out?.items) && out.items.length ? out.items : DEFAULT_UPLOAD_MODES;
    uploadModes.value = items;
    selectedUploadMode.value = String(out?.default || DEFAULT_UPLOAD_MODE);
  } catch (_e) {
    uploadModes.value = DEFAULT_UPLOAD_MODES;
    selectedUploadMode.value = DEFAULT_UPLOAD_MODE;
  }
}

async function loadAppConfig() {
  try {
    const out = await apiGet("/api/config");
    appConfig.value = {
      document_delete_enabled: !!out?.document_delete_enabled,
    };
  } catch (_e) {
    appConfig.value = { document_delete_enabled: false };
  }
}

async function loadDocument() {
  if (!selectedDocumentId.value) return;
  try {
    const d = await apiGet(`/api/documents/${encodeURIComponent(selectedDocumentId.value)}`);
    const t = await apiGet(`/api/documents/${encodeURIComponent(selectedDocumentId.value)}/table`);
    selectedDocument.value = d;
    selectedDocumentTable.value = t;
    if (!isForm219.value) {
      collapsed219Groups.value = new Set();
    }
    if (!isForm420.value) {
      collapsed420Rows.value = new Set();
    }
    documentError.value = "";

    const status = String(d.status || "").toLowerCase();
    const stop = status === "error" || status === "duplicate" || (status === "done" && !!t.ready);
    if (stop && docTimer) {
      clearInterval(docTimer);
      docTimer = null;
    }
  } catch (e) {
    documentError.value = e.message || "Ошибка загрузки документа";
  }
}

function openDocument(id) {
  resetDocumentCardState();
  selectedDocumentId.value = id;
  activeTab.value = "document";
  loadDocument();
  docTimer = setInterval(loadDocument, 3000);
}

function isDeleteLocked(doc) {
  const status = String(doc?.status || "").toLowerCase();
  return status === "queued" || status === "processing";
}

async function confirmDeleteDocument(doc) {
  if (!documentDeleteEnabled.value) return;
  if (!doc?.id) return;
  if (isDeleteLocked(doc)) return;
  const label = `${doc.name || doc.id} (${doc.id})`;
  if (!window.confirm(`Удалить документ ${label} из базы и файлов? Это действие нельзя отменить.`)) return;
  try {
    await apiDelete(`/api/documents/${encodeURIComponent(doc.id)}`);
    if (selectedDocumentId.value === doc.id) {
      resetDocumentCardState({ clearSelection: true });
      activeTab.value = "documents";
    }
    await loadDocuments();
  } catch (e) {
    alert(e.message || "Не удалось удалить документ");
  }
}

function resetDocumentCardState(opts = {}) {
  const clearSelection = !!opts.clearSelection;
  closeFormPreview();
  collapsed219Groups.value = new Set();
  collapsed420Rows.value = new Set();
  currentDocumentPage.value = 1;
  selectedDocument.value = null;
  selectedDocumentTable.value = makeEmptyDocumentTable();
  documentError.value = "";
  if (clearSelection) selectedDocumentId.value = "";
  if (docTimer) {
    clearInterval(docTimer);
    docTimer = null;
  }
}

watch(
  () => visibleDocumentRows.value.length,
  () => {
    const maxPage = documentTotalPages.value;
    if (currentDocumentPage.value > maxPage) currentDocumentPage.value = maxPage;
    if (currentDocumentPage.value < 1) currentDocumentPage.value = 1;
  }
);
watch(
  activeTab,
  (nextTab, prevTab) => {
    if (prevTab === "document" && nextTab !== "document") {
      resetDocumentCardState({ clearSelection: true });
    }
  }
);

onMounted(() => {
  document.addEventListener("click", onDocumentClick);
  if (isAnalyticsRoute) return;
  Promise.allSettled([loadUploadModes(), loadDocuments(), loadAppConfig()]);
  docsTimer = setInterval(loadDocuments, 3000);
});

onBeforeUnmount(() => {
  resetDocumentCardState({ clearSelection: true });
  document.removeEventListener("click", onDocumentClick);
  if (docsTimer) clearInterval(docsTimer);
  uploadFiles.value.forEach((f) => URL.revokeObjectURL(f.url));
});
</script>
