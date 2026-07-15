<template>
  <div class="app-shell">
    <header class="topbar">
      <div class="topbar-inner">
        <div class="brand-wrap">
          <div class="brand-copy">
            <div class="brand-title">PDF/Analytics</div>
            <div class="brand-sub">Панель анализа финансовых поступлений</div>
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
          <a class="btn active" :href="analyticsUrl">Аналитика</a>
        </nav>
      </div>
    </header>

    <main class="content">
      <section class="card filters">
        <div class="filters-head">
          <h2>Фильтры</h2>
          <span class="filters-status" :class="{ ok: canLoad && !errorText }">{{ canLoad && !errorText ? "Данные загружены" : "Ожидание фильтров" }}</span>
        </div>
        <div class="filters-grid filters-grid-wide">
          <label class="field">
            <span>Регион</span>
            <select v-model="selectedRegion">
              <option value="" disabled>Выберите регион</option>
              <option v-for="x in filters.regions" :key="x" :value="x">{{ x }}</option>
            </select>
          </label>
          <label class="field">
            <span>Период</span>
            <select v-model="selectedPeriod">
              <option value="" disabled>Выберите период</option>
              <option value="all">Все периоды</option>
              <option v-for="x in availablePeriods" :key="x" :value="x">{{ x }}</option>
            </select>
          </label>
          <label class="field">
            <span>КБК</span>
            <select v-model="selectedKbk">
              <option value="">Все КБК</option>
              <option v-for="x in availableKbks" :key="x" :value="x">{{ x }}</option>
            </select>
          </label>
          <label class="field">
            <span>Банк</span>
            <select v-model="selectedBank">
              <option value="">Все банки</option>
              <option v-for="x in filters.banks" :key="x" :value="x">{{ x }}</option>
            </select>
          </label>
          <label class="field">
            <span>Категория</span>
            <select v-model="selectedCategory">
              <option value="">Все</option>
              <option v-for="x in filters.categories" :key="x" :value="x">{{ x }}</option>
            </select>
          </label>
          <label class="field">
            <span>МСБ</span>
            <select v-model="selectedMsb">
              <option value="">Все</option>
              <option v-for="x in msbFilterOptions" :key="x" :value="x">{{ x }}</option>
            </select>
          </label>
          <label class="field">
            <span>ОКЭД</span>
            <select v-model="selectedOked">
              <option value="">Все</option>
              <option v-for="x in okedOptions" :key="x.code" :value="x.code">{{ x.label }}</option>
            </select>
          </label>
          <label class="field">
            <span>Поиск ИИН/БИН</span>
            <input v-model.trim="topSearch" type="text" placeholder="ИИН/БИН или название..." />
          </label>
        </div>
        <p class="muted" v-if="!canLoad">Выберите регион и период для загрузки.</p>
        <p class="muted" v-if="okedNote">{{ okedNote }}</p>
        <p class="muted error" v-if="errorText">{{ errorText }}</p>
      </section>

      <div class="analytics-layout">
        <aside class="analytics-side card">
          <div class="analytics-side-title">Навигация</div>
          <button class="side-tab" :class="{ active: analyticsTab === 'kpi_top' }" @click="analyticsTab = 'kpi_top'">KPI и TOP</button>
          <button class="side-tab" :class="{ active: analyticsTab === 'summary_msb_oked' }" @click="analyticsTab = 'summary_msb_oked'">Свод / МСБ / ОКЭД</button>
          <button class="side-tab" :class="{ active: analyticsTab === 'iin_bin' }" @click="analyticsTab = 'iin_bin'">ИИН / БИН</button>
        </aside>

        <div class="analytics-main">
      <section v-if="analyticsTab === 'kpi_top'" class="kpi-grid kpi-grid-wide">
        <article class="card kpi kpi-1">
          <div class="kpi-head"><div class="kpi-label">Общая сумма</div><div class="kpi-icon">₸</div></div>
          <div class="kpi-value">{{ money(kpi.total_amount) }}</div>
          <div class="kpi-sub">Всего поступлений</div>
        </article>
        <article class="card kpi kpi-2">
          <div class="kpi-head"><div class="kpi-label">YoY</div><div class="kpi-icon">↗</div></div>
          <div class="kpi-value" :class="signedPercentClass(kpi.yoy_percent)">{{ percent(kpi.yoy_percent) }}</div>
          <div class="kpi-sub">{{ yoyBaseSubtitle }}</div>
        </article>
        <article class="card kpi kpi-3">
          <div class="kpi-head"><div class="kpi-label">CR (ТОП-10)</div><div class="kpi-icon">◔</div></div>
          <div class="kpi-value">{{ percent(kpi.cr10_percent) }}</div>
          <div class="kpi-sub">Сумма TOP: {{ money(top10Amount) }}</div>
        </article>
        <article class="card kpi kpi-4">
          <div class="kpi-head"><div class="kpi-label">Доля МСБ</div><div class="kpi-icon">▦</div></div>
          <div class="kpi-value">{{ percent(kpi.msb_share_percent) }}</div>
          <div class="kpi-sub">МСБ в общей структуре</div>
        </article>
        <article class="card kpi kpi-5">
          <div class="kpi-head"><div class="kpi-label">Доля ТОП-10</div><div class="kpi-icon">★</div></div>
          <div class="kpi-value">{{ percent(kpi.top10_share_percent) }}</div>
          <div class="kpi-sub">Концентрация поступлений</div>
        </article>
      </section>

      <section v-if="analyticsTab === 'kpi_top'" class="card top-card">
        <div class="section-head">
          <h3>ТОП-аналитика</h3>
          <div class="tabs top-limits">
            <button class="btn top-limit-btn" :class="{ active: topLimit === 5 }" @click="topLimit = 5">TOP-5</button>
            <button class="btn top-limit-btn" :class="{ active: topLimit === 10 }" @click="topLimit = 10">TOP-10</button>
            <button class="btn top-limit-btn" :class="{ active: topLimit === 20 }" @click="topLimit = 20">TOP-20</button>
          </div>
        </div>
        <div class="table-wrap">
          <table class="table top-table">
            <thead><tr><th>#</th><th>ИИН/БИН</th><th>Наименование</th><th>Сумма</th><th>Доля</th><th>YoY</th></tr></thead>
            <tbody>
              <tr v-if="!topRows.length"><td colspan="6" class="muted">Нет данных</td></tr>
              <tr v-for="(x, idx) in topRows" :key="`top_${idx}`" class="clickable-row" @click="openTaxpayerProfile(x)">
                <td>{{ idx + 1 }}</td>
                <td>{{ x.iin_bin || '-' }}</td>
                <td>{{ x.name }}</td>
                <td>{{ money(x.amount) }}</td>
                <td>
                  <div class="share-cell">
                    <div class="share-track"><span class="share-fill" :style="{ width: shareWidth(x.share_percent) }"></span></div>
                    <span>{{ percent(x.share_percent) }}</span>
                  </div>
                </td>
                <td :class="{ positive: (x.change_percent ?? 0) >= 0, negative: (x.change_percent ?? 0) < 0 }">{{ percent(x.change_percent) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="top-footer">
          <div>Концентрация TOP-10: <strong>{{ percent(kpi.top10_share_percent) }}</strong> от общей суммы</div>
          <div>Показано {{ topRows.length }} из {{ topFilteredCount }} плательщиков</div>
        </div>
      </section>

      <section v-if="analyticsTab === 'summary_msb_oked'" class="summary-screen">
        <div class="summary-switch card">
          <button class="btn summary-switch-btn" :class="{ active: summarySectionTab === 'summary' }" @click="summarySectionTab = 'summary'">Свод поступлений</button>
          <button class="btn summary-switch-btn" :class="{ active: summarySectionTab === 'msb' }" @click="summarySectionTab = 'msb'">МСБ</button>
          <button class="btn summary-switch-btn" :class="{ active: summarySectionTab === 'oked' }" @click="summarySectionTab = 'oked'">ОКЭД</button>
        </div>

        <div v-if="summarySectionTab === 'summary'" class="summary-layout">
          <article class="card summary-chart-card">
            <h3>Агрегация по КБК</h3>
            <div ref="summaryDonutChartEl" class="chart chart-sm"></div>
          </article>
          <article class="card summary-table-card">
            <h3>Структура по КБК</h3>
            <div class="table-wrap">
              <table class="table summary-structure-table">
                <thead><tr><th>КБК</th><th>Сумма</th><th>Доля</th></tr></thead>
                <tbody>
                  <tr v-if="!summaryRows.length"><td colspan="3" class="muted">Нет данных</td></tr>
                  <tr v-for="(x, idx) in summaryRows" :key="`summary_${idx}`">
                    <td>{{ x.name }}</td><td>{{ money(x.amount) }}</td><td>{{ percent(x.share_percent) }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </article>
        </div>

        <div v-else-if="summarySectionTab === 'msb'" class="msb-screen">
          <div class="msb-kpi-grid">
            <article class="card msb-kpi-card"><div class="kpi-label">Общая сумма МСБ</div><div class="kpi-value">{{ money(msbTotalAmount) }}</div></article>
            <article class="card msb-kpi-card"><div class="kpi-label">Доля МСБ</div><div class="kpi-value">{{ percent(kpi.msb_share_percent) }}</div></article>
            <article class="card msb-kpi-card"><div class="kpi-label">Количество МСБ</div><div class="kpi-value">{{ msbTaxpayersCount }}</div></article>
          </div>
          <div class="summary-layout">
            <article class="card summary-chart-card">
              <h3>Динамика МСБ</h3>
              <div ref="msbTrendChartEl" class="chart chart-sm"></div>
            </article>
            <article class="card summary-table-card">
              <h3>ТОП-10 МСБ</h3>
              <div class="table-wrap">
                <table class="table">
                  <thead><tr><th>#</th><th>Наименование</th><th>Сумма</th></tr></thead>
                  <tbody>
                    <tr v-if="!msbTop10.length"><td colspan="3" class="muted">Нет данных</td></tr>
                    <tr v-for="(x, idx) in msbTop10" :key="`msb_top_${idx}`" class="clickable-row" @click="openTaxpayerProfile(x)">
                      <td>{{ idx + 1 }}</td><td>{{ x.name }}</td><td>{{ money(x.amount) }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </article>
          </div>
        </div>

        <div v-else class="oked-screen">
          <article class="card">
            <h3>ТОП-10 ОКЭД по сумме поступлений</h3>
            <div ref="okedTopChartEl" class="chart chart-lg"></div>
          </article>
          <article class="card">
            <h3>Детализация по ОКЭД</h3>
            <div class="table-wrap">
              <table class="table">
                <thead><tr><th>ОКЭД</th><th>Сумма</th><th>Доля</th><th>Плательщиков</th></tr></thead>
                <tbody>
                  <tr v-if="!okedRows.length"><td colspan="4" class="muted">Нет данных</td></tr>
                  <tr v-for="(x, idx) in okedRows" :key="`oked_detail_${idx}`">
                    <td>{{ x.oked }} - {{ x.name }}</td><td>{{ money(x.amount) }}</td><td>{{ percent(x.share_percent) }}</td><td>{{ x.taxpayers || 0 }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </article>
        </div>
      </section>

      <section v-if="analyticsTab === 'iin_bin'" class="card taxpayer-card">
        <div class="section-head">
          <h3>Профиль налогоплательщика</h3>
        </div>

        <div class="taxpayer-controls">
          <label class="field">
            <span>ИИН/БИН</span>
            <select v-model="selectedTaxpayer">
              <option value="">Выберите ИИН/БИН</option>
              <option v-for="item in taxpayerOptions" :key="item.iin_bin" :value="item.iin_bin">
                {{ item.iin_bin }} - {{ item.name }}
              </option>
            </select>
          </label>
          <label class="field">
            <span>Сравнение с прошлым годом</span>
            <select v-model="selectedCompareMonth">
              <option value="">Выберите месяц</option>
              <option v-for="month in availableCompareMonths" :key="month" :value="month">{{ month }}</option>
            </select>
          </label>
        </div>

        <div v-if="taxpayerLoading" class="taxpayer-loader">
          <span class="loader-dot"></span>
          <span>Загружаем профиль налогоплательщика...</span>
        </div>
        <p class="muted error" v-else-if="taxpayerError">{{ taxpayerError }}</p>

        <div v-if="!taxpayerLoading && !taxpayerError && effectiveTaxpayerProfile" class="taxpayer-body">
          <div class="taxpayer-headline">
            <div class="taxpayer-name">{{ effectiveTaxpayerProfile.name || "-" }}</div>
            <div class="taxpayer-meta-line">
              <span>ИИН/БИН: {{ effectiveTaxpayerProfile.iin_bin || "-" }}</span>
              <span class="pill">{{ effectiveTaxpayerProfile.segment || "-" }}</span>
            </div>
          </div>

          <div class="taxpayer-top-grid">
            <article class="card profile-card compact">
              <div class="kpi-label">Профиль</div>
              <div class="profile-list">
                <div><span>Регион:</span><strong>{{ effectiveTaxpayerProfile.region || "-" }}</strong></div>
                <div><span>ОКЭД:</span><strong>{{ effectiveTaxpayerProfile.oked || "-" }}</strong></div>
                <div><span>Рейтинг в регионе:</span><strong>#{{ effectiveTaxpayerProfile.rank_region || "-" }} из {{ effectiveTaxpayerProfile.rank_region_total || "-" }}</strong></div>
                <div><span>Рейтинг по ОКЭД:</span><strong>#{{ effectiveTaxpayerProfile.rank_oked || "-" }} из {{ effectiveTaxpayerProfile.rank_oked_total || "-" }}</strong></div>
              </div>
            </article>

            <article class="card profile-card compact">
              <div class="kpi-label">Период</div>
              <div class="profile-pairs">
                <div><span>Текущий:</span><strong>{{ money(effectiveTaxpayerProfile.current_period_amount) }}</strong></div>
                <div><span>Прошлый год:</span><strong>{{ money(effectiveTaxpayerProfile.prev_year_amount) }}</strong></div>
                <div><span>YoY:</span><strong :class="signedPercentClass(effectiveTaxpayerProfile.yoy_percent)">{{ percent(effectiveTaxpayerProfile.yoy_percent) }}</strong></div>
              </div>
            </article>

            <article class="card profile-card compact">
              <div class="kpi-label">Итоги</div>
              <div class="profile-pairs">
                <div><span>Годовая сумма:</span><strong>{{ money(effectiveTaxpayerProfile.annual_amount) }}</strong></div>
                <div><span>Среднемесячный:</span><strong>{{ money(effectiveTaxpayerProfile.avg_monthly) }}</strong></div>
                <div><span>Прогноз (3 мес):</span><strong>{{ money(effectiveTaxpayerProfile.forecast_3m) }}</strong></div>
              </div>
            </article>
          </div>

          <div class="taxpayer-health-grid">
            <article class="card profile-card compact"><div class="kpi-label">Индекс стабильности</div><div class="profile-value">{{ intCompact(effectiveTaxpayerProfile.stability_index_percent) }}%</div></article>
            <article class="card profile-card compact"><div class="kpi-label">Индикатор риска</div><div class="profile-value">{{ effectiveTaxpayerProfile.risk_level || "-" }}</div></article>
            <article class="card profile-card compact"><div class="kpi-label">Диверсификация КБК</div><div class="profile-value">{{ effectiveTaxpayerProfile.kbk_diversification_count || 0 }} КБК</div></article>
          </div>

          <div class="summary-layout">
            <article class="card summary-chart-card">
              <h3>Динамика поступлений</h3>
              <div ref="taxpayerDynamicsChartEl" class="chart chart-sm"></div>
            </article>
            <article class="card summary-chart-card">
              <h3>Структура по КБК</h3>
              <div ref="taxpayerKbkChartEl" class="chart chart-sm"></div>
            </article>
          </div>

          <div class="card">
            <h3>Анализ сезонности</h3>
            <div class="profile-grid profile-grid-4">
              <div><div class="kpi-label">Пиковый месяц</div><div class="profile-value">{{ taxpayerSeasonality?.peak_period || "-" }} - {{ money(taxpayerSeasonality?.peak_amount) }}</div></div>
              <div><div class="kpi-label">Минимальный месяц</div><div class="profile-value">{{ taxpayerSeasonality?.min_period || "-" }} - {{ money(taxpayerSeasonality?.min_amount) }}</div></div>
              <div><div class="kpi-label">Разброс</div><div class="profile-value">{{ percent(taxpayerSeasonality?.spread_percent) }}</div></div>
              <div><div class="kpi-label">Прогноз (3 мес)</div><div class="profile-value">{{ money(taxpayerSeasonality?.forecast_3m) }}</div></div>
            </div>
          </div>

          <div class="card taxpayer-period-table-card">
            <div class="section-head">
              <h3>Сравнение поступлений по периодам <span v-if="taxpayerComparisonYear">({{ taxpayerComparisonYear }})</span></h3>
              <div class="tabs top-limits">
                <button class="btn top-limit-btn" :class="{ active: taxpayerComparisonMode === 'monthly' }" @click="taxpayerComparisonMode = 'monthly'">По месяцам</button>
                <button class="btn top-limit-btn" :class="{ active: taxpayerComparisonMode === 'quarterly' }" @click="taxpayerComparisonMode = 'quarterly'">По кварталам</button>
                <button class="btn top-limit-btn" :class="{ active: taxpayerComparisonMode === 'aggregated' }" @click="taxpayerComparisonMode = 'aggregated'">Агрегировано</button>
              </div>
            </div>
            <div class="table-wrap taxpayer-period-table-wrap">
              <table class="table taxpayer-period-table">
                <thead>
                  <tr v-if="taxpayerComparisonMode === 'monthly'">
                    <th>ИИН/БИН</th>
                    <th>Наименование</th>
                    <th v-for="m in comparisonMonthHeaders" :key="`h_m_${m.key}`">{{ m.label }}</th>
                    <th>Итого</th>
                  </tr>
                  <tr v-else-if="taxpayerComparisonMode === 'quarterly'">
                    <th>ИИН/БИН</th>
                    <th>Наименование</th>
                    <th>Q1</th>
                    <th>Q2</th>
                    <th>Q3</th>
                    <th>Q4</th>
                    <th>Итого</th>
                  </tr>
                  <tr v-else>
                    <th>ИИН/БИН</th>
                    <th>Наименование</th>
                    <th>Поступления (агрегировано)</th>
                    <th>Итого</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-if="!taxpayerComparisonRows.length">
                    <td :colspan="taxpayerComparisonMode === 'monthly' ? 15 : (taxpayerComparisonMode === 'quarterly' ? 7 : 4)" class="muted">Нет данных</td>
                  </tr>
                  <tr v-for="row in taxpayerComparisonRows" :key="`cmp_${taxpayerComparisonMode}_${row.iin_bin}`" class="clickable-row" @click="openTaxpayerProfile(row)">
                    <td>{{ row.iin_bin || "-" }}</td>
                    <td>{{ row.name || "-" }}</td>
                    <template v-if="taxpayerComparisonMode === 'monthly'">
                      <td v-for="m in comparisonMonthHeaders" :key="`m_${row.iin_bin}_${m.key}`">{{ money(row[`m_${m.key}`]) }}</td>
                      <td><strong>{{ money(row.total) }}</strong></td>
                    </template>
                    <template v-else-if="taxpayerComparisonMode === 'quarterly'">
                      <td>{{ money(row.q1) }}</td>
                      <td>{{ money(row.q2) }}</td>
                      <td>{{ money(row.q3) }}</td>
                      <td>{{ money(row.q4) }}</td>
                      <td><strong>{{ money(row.total) }}</strong></td>
                    </template>
                    <template v-else>
                      <td>{{ money(row.amount) }}</td>
                      <td><strong>{{ money(row.total) }}</strong></td>
                    </template>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>
        <p v-else-if="!taxpayerLoading && !taxpayerError && !selectedTaxpayer" class="muted">Выберите ИИН/БИН для загрузки профиля.</p>
        <p v-else-if="!taxpayerLoading && !taxpayerError" class="muted">Нет данных по выбранному ИИН/БИН.</p>
      </section>
        </div>
      </div>
    </main>
  </div>
</template>

<script setup>
import Highcharts from "highcharts/es-modules/masters/highcharts.src.js";
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { buildAnalyticsPath, buildFormPath, listFormProfiles } from "../formProfiles";

function resolveApiBase() {
  const host = String(window.location.hostname || "").toLowerCase();
  if (host.endsWith(".e-qoldau.asia")) return "https://api.e-qoldau.asia";
  return String(import.meta.env.VITE_API_BASE || "https://api.e-qoldau.asia").replace(/\/+$/, "");
}

const API_BASE = resolveApiBase();
const analyticsUrl = buildAnalyticsPath();
const SITE_LINKS = listFormProfiles().map((profile) => ({
  id: profile.formId,
  label: profile.formLabel,
  url: buildFormPath(profile.slug),
}));
const MSB_FILTER_OPTIONS = [
  "Микро предпринимательство",
  "Малое предпринимательство",
  "Среднее предпринимательство",
  "Крупное предпринимательство",
  "Не определено",
];

const filters = ref({ regions: [], periods: [], kbks: [], banks: [], categories: [], okeds: [], oked_catalog: [], msb_segments: [], periods_by_region: {}, kbks_by_region: {}, kbks_by_region_period: {} });
const selectedRegion = ref("");
const selectedPeriod = ref("");
const selectedKbk = ref("");
const selectedBank = ref("");
const selectedCategory = ref("");
const selectedMsb = ref("");
const selectedOked = ref("");
const summarySectionTab = ref("summary");
const topLimit = ref(10);
const topSearch = ref("");
const analyticsTab = ref("kpi_top");
const errorText = ref("");
const okedNote = ref("");
const siteSwitchOpen = ref(false);

const selectedTaxpayer = ref("");
const selectedCompareMonth = ref("");
const taxpayerOptions = ref([]);
const taxpayerMonthlyRows = ref([]);
const taxpayerQuarterlyRows = ref([]);
const taxpayerCompare = ref(null);
const availableCompareMonths = ref([]);
const taxpayerLoading = ref(false);
const taxpayerError = ref("");
const taxpayerProfile = ref(null);
const taxpayerYearCompare = ref([]);
const taxpayerKbkStructure = ref([]);
const taxpayerSeasonality = ref(null);
const taxpayerComparisonMode = ref("monthly");
const taxpayerComparisonTable = ref({ year: null, monthly_rows: [], quarterly_rows: [], aggregated_rows: [] });

const kpi = ref({ total_amount: 0, prev_total_amount: null, yoy_percent: null, unique_taxpayers: 0, top10_share_percent: 0, msb_share_percent: 0, cr10_percent: 0 });
const summaryByKbk = ref([]);
const topAnalytics = ref([]);
const msbBreakdown = ref([]);
const msbTop10 = ref([]);
const okedTable = ref([]);
const seriesMsbMonthly = ref([]);

const summaryDonutChartEl = ref(null);
const msbTrendChartEl = ref(null);
const okedTopChartEl = ref(null);
const taxpayerDynamicsChartEl = ref(null);
const taxpayerKbkChartEl = ref(null);
let summaryDonutChart = null;
let msbTrendChart = null;
let okedTopChart = null;
let taxpayerChart = null;
let taxpayerKbkChart = null;
let taxpayerRequestSeq = 0;
let suppressTaxpayerWatch = false;

const siteLinks = computed(() => SITE_LINKS);
const msbFilterOptions = computed(() => MSB_FILTER_OPTIONS);
const canLoad = computed(() => !!selectedRegion.value && !!selectedPeriod.value);
const availablePeriods = computed(() => {
  const p = filters.value.periods_by_region?.[selectedRegion.value];
  return Array.isArray(p) && p.length ? p : filters.value.periods;
});
const availableKbks = computed(() => {
  const region = selectedRegion.value;
  const period = selectedPeriod.value;
  if (period === "all") return filters.value.kbks_by_region?.[region] || filters.value.kbks;
  const byRegionPeriod = filters.value.kbks_by_region_period?.[region];
  if (Array.isArray(byRegionPeriod?.[period]) && byRegionPeriod[period].length) return byRegionPeriod[period];
  return filters.value.kbks_by_region?.[region] || filters.value.kbks;
});
const summaryRows = computed(() => summaryByKbk.value);
const topFiltered = computed(() => {
  const q = topSearch.value.trim().toLowerCase();
  if (!q) return topAnalytics.value;
  return topAnalytics.value.filter((x) => {
    const iin = String(x?.iin_bin || "").toLowerCase();
    const name = String(x?.name || "").toLowerCase();
    return iin.includes(q) || name.includes(q);
  });
});
const topFilteredCount = computed(() => topFiltered.value.length);
const topRows = computed(() => topFiltered.value.slice(0, topLimit.value));
const okedRows = computed(() => okedTable.value);
const okedOptions = computed(() => {
  const catalog = Array.isArray(filters.value.oked_catalog) ? filters.value.oked_catalog : [];
  if (catalog.length) {
    const seen = new Set();
    return catalog
      .map((item) => {
        const code = String(item?.code || "").trim();
        const name = String(item?.name || "").trim();
        if (!code || seen.has(code)) return null;
        seen.add(code);
        return { code, label: name ? `${code} - ${name}` : code };
      })
      .filter(Boolean);
  }
  return (Array.isArray(filters.value.okeds) ? filters.value.okeds : []).map((code) => {
    const value = String(code || "").trim();
    return { code: value, label: value };
  });
});
const previousTotalAmount = computed(() => {
  const raw = kpi.value?.prev_total_amount;
  if (raw == null) return null;
  const total = Number(raw);
  return Number.isFinite(total) ? total : null;
});
const yoyBaseSubtitle = computed(() => {
  if (kpi.value?.yoy_percent == null) return "Нет базы прошлого года";
  if (previousTotalAmount.value == null) return "Прошлый год: -";
  return `Прошлый год: ${money(previousTotalAmount.value)}`;
});
const top10Amount = computed(() => Number(kpi.value?.total_amount || 0) * (Number(kpi.value?.top10_share_percent || 0) / 100));
const msbTotalAmount = computed(() => Number(kpi.value?.total_amount || 0) * (Number(kpi.value?.msb_share_percent || 0) / 100));
const msbTaxpayersCount = computed(() => {
  const rows = Array.isArray(msbBreakdown.value) ? msbBreakdown.value : [];
  return rows
    .filter((x) => String(x?.segment || "") !== "Крупный")
    .reduce((acc, x) => acc + Number(x?.taxpayers || 0), 0);
});
const effectiveTaxpayerProfile = computed(() => {
  if (taxpayerProfile.value) return taxpayerProfile.value;
  const iin = String(selectedTaxpayer.value || "");
  if (!iin) return null;
  const option = taxpayerOptions.value.find((x) => String(x?.iin_bin || "") === iin);
  if (!option) return null;
  const cmp = taxpayerCompare.value || {};
  const yearly = taxpayerYearCompare.value || [];
  const annual = yearly.reduce((acc, x) => acc + Number(x?.current_amount || 0), 0);
  const avgMonthly = yearly.length ? annual / yearly.length : 0;
  const kbkCount = (taxpayerKbkStructure.value || []).length;
  return {
    name: String(option?.name || "-"),
    iin_bin: String(option?.iin_bin || "-"),
    segment: "МСБ",
    region: String(selectedRegion.value || "-"),
    oked: "-",
    rank_region: "-",
    rank_region_total: "-",
    rank_oked: "-",
    rank_oked_total: "-",
    current_period_amount: Number(cmp?.current_amount || 0),
    prev_year_amount: Number(cmp?.prev_amount || 0),
    yoy_percent: cmp?.diff_percent == null ? null : Number(cmp.diff_percent),
    annual_amount: annual,
    avg_monthly: avgMonthly,
    stability_index_percent: 0,
    risk_level: "-",
    kbk_diversification_count: kbkCount,
    forecast_3m: Number(taxpayerSeasonality.value?.forecast_3m || 0),
  };
});
const comparisonMonthHeaders = [
  { key: "01", label: "Янв" }, { key: "02", label: "Фев" }, { key: "03", label: "Мар" }, { key: "04", label: "Апр" },
  { key: "05", label: "Май" }, { key: "06", label: "Июн" }, { key: "07", label: "Июл" }, { key: "08", label: "Авг" },
  { key: "09", label: "Сен" }, { key: "10", label: "Окт" }, { key: "11", label: "Ноя" }, { key: "12", label: "Дек" },
];
const taxpayerComparisonYear = computed(() => String(taxpayerComparisonTable.value?.year || ""));
const taxpayerComparisonRows = computed(() => {
  const table = taxpayerComparisonTable.value || {};
  if (taxpayerComparisonMode.value === "quarterly") return Array.isArray(table.quarterly_rows) ? table.quarterly_rows : [];
  if (taxpayerComparisonMode.value === "aggregated") return Array.isArray(table.aggregated_rows) ? table.aggregated_rows : [];
  return Array.isArray(table.monthly_rows) ? table.monthly_rows : [];
});

function money(v) {
  const num = Number(v || 0);
  if (!Number.isFinite(num)) return "0";
  const abs = Math.abs(num);
  const fmt = (value) => {
    const rounded = Math.round(value * 10) / 10;
    const fractionDigits = Number.isInteger(rounded) ? 0 : 1;
    return new Intl.NumberFormat("ru-RU", { minimumFractionDigits: fractionDigits, maximumFractionDigits: 1 }).format(rounded);
  };
  if (abs >= 1_000_000_000) return `${fmt(num / 1_000_000_000)} млрд`;
  if (abs >= 1_000_000) return `${fmt(num / 1_000_000)} млн`;
  if (abs >= 1_000) return `${fmt(num / 1_000)} тыс`;
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(num);
}
function percent(v) { if (v == null || Number.isNaN(Number(v))) return "-"; return `${Number(v).toFixed(2)}%`; }
function signedPercentClass(v) {
  if (v == null || Number.isNaN(Number(v))) return {};
  return { positive: Number(v) >= 0, negative: Number(v) < 0 };
}
function intCompact(v) {
  const n = Number(v || 0);
  if (!Number.isFinite(n)) return "0";
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(Math.round(n));
}
function shareWidth(v) {
  const num = Number(v || 0);
  if (!Number.isFinite(num)) return "0%";
  const bounded = Math.max(0, Math.min(100, num));
  return `${bounded.toFixed(2)}%`;
}
function monthShort(period) {
  const m = String(period || "").match(/^\d{4}-(\d{2})$/);
  const labels = ["Янв", "Фев", "Мар", "Апр", "Май", "Июн", "Июл", "Авг", "Сен", "Окт", "Ноя", "Дек"];
  if (!m) return String(period || "");
  const idx = Number(m[1]) - 1;
  return labels[idx] || String(period || "");
}

async function apiGet(path) {
  const res = await fetch(`${API_BASE}${path}`);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || "Request failed");
  return data;
}

function toggleSiteSwitch() { siteSwitchOpen.value = !siteSwitchOpen.value; }
function onDocumentClick() { siteSwitchOpen.value = false; }

async function loadFilters() {
  const out = await apiGet("/api/analytics/243/filters");
  filters.value = {
    regions: Array.isArray(out.regions) ? out.regions : [],
    periods: Array.isArray(out.periods) ? out.periods : [],
    kbks: Array.isArray(out.kbks) ? out.kbks : [],
    banks: Array.isArray(out.banks) ? out.banks : [],
    categories: Array.isArray(out.categories) ? out.categories : [],
    okeds: Array.isArray(out.okeds) ? out.okeds : [],
    oked_catalog: Array.isArray(out.oked_catalog) ? out.oked_catalog : [],
    msb_segments: Array.isArray(out.msb_segments) ? out.msb_segments : [],
    periods_by_region: out.periods_by_region || {},
    kbks_by_region: out.kbks_by_region || {},
    kbks_by_region_period: out.kbks_by_region_period || {},
  };
  const savedRegion = String(localStorage.getItem("ANALYTICS_REGION") || "");
  if (savedRegion && filters.value.regions.includes(savedRegion)) selectedRegion.value = savedRegion;
  else if (!selectedRegion.value && filters.value.regions.length) selectedRegion.value = filters.value.regions[0];
  const periodList = Array.isArray(filters.value.periods_by_region?.[selectedRegion.value]) ? filters.value.periods_by_region[selectedRegion.value] : filters.value.periods;
  selectedPeriod.value = periodList.length ? periodList[0] : "";
  if (!msbFilterOptions.value.includes(String(selectedMsb.value || ""))) selectedMsb.value = "";
}

function buildOverviewPath() {
  const qp = new URLSearchParams();
  qp.set("region", selectedRegion.value);
  qp.set("period", selectedPeriod.value);
  if (selectedKbk.value) qp.set("kbk", selectedKbk.value);
  if (selectedBank.value) qp.set("bank", selectedBank.value);
  if (selectedCategory.value) qp.set("category", selectedCategory.value);
  if (selectedMsb.value) qp.set("msb", selectedMsb.value);
  if (selectedOked.value) qp.set("oked", selectedOked.value);
  return `/api/analytics/243/overview?${qp.toString()}`;
}

function buildTaxpayerDynamicsPath() {
  const qp = new URLSearchParams();
  qp.set("region", selectedRegion.value);
  qp.set("period", selectedPeriod.value);
  if (selectedKbk.value) qp.set("kbk", selectedKbk.value);
  if (selectedBank.value) qp.set("bank", selectedBank.value);
  if (selectedCategory.value) qp.set("category", selectedCategory.value);
  if (selectedMsb.value) qp.set("msb", selectedMsb.value);
  if (selectedOked.value) qp.set("oked", selectedOked.value);
  if (selectedTaxpayer.value) qp.set("iin_bin", selectedTaxpayer.value);
  if (selectedCompareMonth.value) qp.set("compare_month", selectedCompareMonth.value);
  return `/api/analytics/243/taxpayer-dynamics?${qp.toString()}`;
}

function zeroState() {
  kpi.value = { total_amount: 0, prev_total_amount: null, yoy_percent: null, unique_taxpayers: 0, top10_share_percent: 0, msb_share_percent: 0, cr10_percent: 0 };
  summaryByKbk.value = [];
  topAnalytics.value = [];
  msbBreakdown.value = [];
  msbTop10.value = [];
  okedTable.value = [];
  seriesMsbMonthly.value = [];
  okedNote.value = "";
  renderCharts();
}

function zeroTaxpayerState() {
  taxpayerOptions.value = [];
  taxpayerMonthlyRows.value = [];
  taxpayerQuarterlyRows.value = [];
  taxpayerCompare.value = null;
  availableCompareMonths.value = [];
  selectedTaxpayer.value = "";
  selectedCompareMonth.value = "";
  taxpayerError.value = "";
  taxpayerLoading.value = false;
  taxpayerProfile.value = null;
  taxpayerYearCompare.value = [];
  taxpayerKbkStructure.value = [];
  taxpayerSeasonality.value = null;
  taxpayerComparisonTable.value = { year: null, monthly_rows: [], quarterly_rows: [], aggregated_rows: [] };
  renderTaxpayerChart();
}

async function loadOverview() {
  if (!canLoad.value) return zeroState();
  const out = await apiGet(buildOverviewPath());
  kpi.value = {
    total_amount: Number(out?.kpi?.total_amount || 0),
    prev_total_amount: out?.kpi?.prev_total_amount == null ? null : Number(out.kpi.prev_total_amount),
    yoy_percent: out?.kpi?.yoy_percent == null ? null : Number(out.kpi.yoy_percent),
    unique_taxpayers: Number(out?.kpi?.unique_taxpayers || 0),
    top10_share_percent: Number(out?.kpi?.top10_share_percent || 0),
    msb_share_percent: Number(out?.kpi?.msb_share_percent || 0),
    cr10_percent: Number(out?.kpi?.cr10_percent || 0),
  };
  summaryByKbk.value = Array.isArray(out.summary_by_kbk) ? out.summary_by_kbk : [];
  topAnalytics.value = Array.isArray(out.top_analytics) ? out.top_analytics : [];
  msbBreakdown.value = Array.isArray(out.msb_breakdown) ? out.msb_breakdown : [];
  msbTop10.value = Array.isArray(out.msb_top10) ? out.msb_top10 : [];
  okedTable.value = Array.isArray(out.oked_table) ? out.oked_table : [];
  seriesMsbMonthly.value = Array.isArray(out.series_msb_monthly) ? out.series_msb_monthly : [];
  okedNote.value = String(out?.meta?.oked_note || "");
  renderCharts();
}

async function loadTaxpayerDynamics() {
  if (!canLoad.value) return zeroTaxpayerState();
  if (!selectedTaxpayer.value && analyticsTab.value !== "iin_bin") return;
  const reqId = ++taxpayerRequestSeq;
  taxpayerLoading.value = true;
  taxpayerError.value = "";
  try {
    const out = await apiGet(buildTaxpayerDynamicsPath());
    if (reqId !== taxpayerRequestSeq) return;
    taxpayerOptions.value = Array.isArray(out.taxpayers) ? out.taxpayers : [];
    taxpayerMonthlyRows.value = Array.isArray(out.series_monthly) ? out.series_monthly : [];
    taxpayerQuarterlyRows.value = Array.isArray(out.series_quarterly) ? out.series_quarterly : [];
    taxpayerCompare.value = out.compare_month || null;
    availableCompareMonths.value = Array.isArray(out.available_months) ? out.available_months : [];
    taxpayerProfile.value = out.profile || null;
    taxpayerYearCompare.value = Array.isArray(out.series_year_compare) ? out.series_year_compare : [];
    taxpayerKbkStructure.value = Array.isArray(out.kbk_structure) ? out.kbk_structure : [];
    taxpayerSeasonality.value = out.seasonality || null;
    taxpayerComparisonTable.value = out.comparison_table || { year: null, monthly_rows: [], quarterly_rows: [], aggregated_rows: [] };

    renderTaxpayerChart();
  } catch (e) {
    if (reqId !== taxpayerRequestSeq) return;
    taxpayerMonthlyRows.value = [];
    taxpayerQuarterlyRows.value = [];
    taxpayerCompare.value = null;
    taxpayerProfile.value = null;
    taxpayerYearCompare.value = [];
    taxpayerKbkStructure.value = [];
    taxpayerSeasonality.value = null;
    taxpayerComparisonTable.value = { year: null, monthly_rows: [], quarterly_rows: [], aggregated_rows: [] };
    taxpayerError.value = e?.message || "Ошибка загрузки динамики по ИИН/БИН";
    renderTaxpayerChart();
  } finally {
    taxpayerLoading.value = false;
  }
}

function renderSummaryDonutChart() {
  if (!summaryDonutChartEl.value) return;
  summaryDonutChart?.destroy();
  const rows = summaryRows.value.slice(0, 10);
  summaryDonutChart = Highcharts.chart(summaryDonutChartEl.value, {
    chart: { type: "pie", backgroundColor: "transparent" },
    title: { text: null },
    credits: { enabled: false },
    plotOptions: { pie: { innerSize: "58%", dataLabels: { enabled: false } } },
    tooltip: {
      pointFormatter() {
        return `<span style="color:${this.color}">●</span> ${this.name}: <b>${money(this.y)}</b><br/>`;
      },
    },
    series: [{
      name: "Сумма",
      colorByPoint: true,
      data: rows.map((x) => ({ name: x.name, y: Number(x.amount || 0) })),
      colors: ["#3f7ee8", "#18b37f", "#f19b0d", "#6a8ecb", "#55c4b2", "#3d596f"],
    }],
  });
}

function renderMsbTrendChart() {
  if (!msbTrendChartEl.value) return;
  msbTrendChart?.destroy();
  const rows = seriesMsbMonthly.value.slice(-12);
  msbTrendChart = Highcharts.chart(msbTrendChartEl.value, {
    chart: { type: "line", backgroundColor: "transparent" },
    title: { text: null },
    credits: { enabled: false },
    xAxis: { categories: rows.map((x) => monthShort(x.period)), lineColor: "#16423c", tickColor: "#16423c" },
    yAxis: {
      title: { text: "Сумма" },
      gridLineColor: "#d6ebe5",
      labels: { formatter() { return money(this.value); } },
    },
    tooltip: {
      pointFormatter() {
        return `<span style="color:${this.color}">●</span> ${this.series.name}: <b>${money(this.y)}</b><br/>`;
      },
    },
    series: [
      { name: "МСБ", data: rows.map((x) => Number(x.msb_amount || 0)), color: "#11b3a4" },
      { name: "Не МСБ", data: rows.map((x) => Number(x.non_msb_amount || 0)), color: "#5f6ff2" },
    ],
  });
}

function renderOkedTopChart() {
  if (!okedTopChartEl.value) return;
  okedTopChart?.destroy();
  const rows = okedRows.value.slice(0, 10);
  okedTopChart = Highcharts.chart(okedTopChartEl.value, {
    chart: { type: "bar", backgroundColor: "transparent" },
    title: { text: null },
    credits: { enabled: false },
    legend: { enabled: false },
    xAxis: { categories: rows.map((x) => x.name), lineColor: "#16423c", tickColor: "#16423c" },
    yAxis: {
      title: { text: "Сумма" },
      gridLineColor: "#d6ebe5",
      labels: { formatter() { return money(this.value); } },
    },
    tooltip: {
      pointFormatter() {
        return `<span style="color:${this.color}">●</span> ${this.series.name}: <b>${money(this.y)}</b><br/>`;
      },
    },
    series: [{ name: "Сумма", data: rows.map((x) => Number(x.amount || 0)), color: "#3f7ee8" }],
  });
}

function renderTaxpayerChart() {
  if (!taxpayerDynamicsChartEl.value) return;
  taxpayerChart?.destroy();
  const rows = taxpayerYearCompare.value;
  taxpayerChart = Highcharts.chart(taxpayerDynamicsChartEl.value, {
    chart: { type: "line", backgroundColor: "transparent" },
    title: { text: null }, credits: { enabled: false }, legend: { enabled: true },
    xAxis: { categories: rows.map((x) => monthShort(`2025-${x.month}`)), lineColor: "#16423c", tickColor: "#16423c" },
    yAxis: {
      title: { text: "Сумма" },
      gridLineColor: "#d6ebe5",
      labels: { formatter() { return money(this.value); } },
    },
    tooltip: {
      pointFormatter() {
        return `<span style="color:${this.color}">●</span> ${this.series.name}: <b>${money(this.y)}</b><br/>`;
      },
    },
    series: [
      { name: "Текущий год", data: rows.map((x) => Number(x.current_amount || 0)), color: "#3f7ee8" },
      { name: "Прошлый год", data: rows.map((x) => Number(x.prev_amount || 0)), color: "#8a9cb8", dashStyle: "ShortDash" },
    ],
  });
  if (!taxpayerKbkChartEl.value) return;
  taxpayerKbkChart?.destroy();
  taxpayerKbkChart = Highcharts.chart(taxpayerKbkChartEl.value, {
    chart: { type: "pie", backgroundColor: "transparent" },
    title: { text: null }, credits: { enabled: false },
    plotOptions: { pie: { innerSize: "58%", dataLabels: { enabled: false } } },
    tooltip: {
      pointFormatter() {
        return `<span style="color:${this.color}">●</span> ${this.name}: <b>${money(this.y)}</b><br/>`;
      },
    },
    series: [{
      name: "КБК",
      colorByPoint: true,
      data: taxpayerKbkStructure.value.map((x) => ({ name: x.kbk, y: Number(x.amount || 0) })),
      colors: ["#3f7ee8", "#18b37f", "#f19b0d", "#6a8ecb", "#55c4b2", "#3d596f"],
    }],
  });
}

async function openTaxpayerProfile(row) {
  const iin = String(row?.iin_bin || "").trim();
  if (!iin || iin === "-") return;
  suppressTaxpayerWatch = true;
  taxpayerLoading.value = true;
  taxpayerProfile.value = null;
  taxpayerYearCompare.value = [];
  taxpayerKbkStructure.value = [];
  taxpayerSeasonality.value = null;
  analyticsTab.value = "iin_bin";
  selectedTaxpayer.value = iin;
  selectedCompareMonth.value = "";
  await nextTick();
  suppressTaxpayerWatch = false;
  await loadTaxpayerDynamics();
}

function renderCharts() {
  if (summarySectionTab.value === "summary") renderSummaryDonutChart();
  if (summarySectionTab.value === "msb") renderMsbTrendChart();
  if (summarySectionTab.value === "oked") renderOkedTopChart();
}

watch(summarySectionTab, async () => {
  await nextTick();
  renderCharts();
});
watch(analyticsTab, async (tab) => {
  await nextTick();
  if (tab === "summary_msb_oked") {
    renderCharts();
    return;
  }
  if (tab === "iin_bin") {
    if (!taxpayerLoading.value) {
      try { await loadTaxpayerDynamics(); } catch (_) { /* handled */ }
    }
    renderTaxpayerChart();
  }
});
watch(selectedRegion, (v) => {
  localStorage.setItem("ANALYTICS_REGION", String(v || ""));
  const periodList = Array.isArray(filters.value.periods_by_region?.[v]) ? filters.value.periods_by_region[v] : [];
  if (selectedPeriod.value !== "all" && periodList.length && !periodList.includes(selectedPeriod.value)) selectedPeriod.value = periodList[0];
  if (selectedKbk.value && !availableKbks.value.includes(selectedKbk.value)) selectedKbk.value = "";
});
watch(selectedPeriod, () => { if (selectedKbk.value && !availableKbks.value.includes(selectedKbk.value)) selectedKbk.value = ""; });
watch(filters, () => {
  if (selectedBank.value && !filters.value.banks.includes(selectedBank.value)) selectedBank.value = "";
  if (selectedCategory.value && !filters.value.categories.includes(selectedCategory.value)) selectedCategory.value = "";
  if (selectedOked.value && !okedOptions.value.some((x) => x.code === selectedOked.value)) selectedOked.value = "";
  if (selectedMsb.value && !msbFilterOptions.value.includes(selectedMsb.value)) selectedMsb.value = "";
}, { deep: true });
watch([selectedRegion, selectedPeriod, selectedKbk, selectedBank, selectedCategory, selectedMsb, selectedOked], async () => {
  errorText.value = "";
  taxpayerError.value = "";
  try {
    await loadOverview();
    if (analyticsTab.value === "iin_bin" || selectedTaxpayer.value) await loadTaxpayerDynamics();
  } catch (e) {
    errorText.value = e?.message || "Ошибка загрузки аналитики";
  }
});
watch([selectedTaxpayer, selectedCompareMonth], async () => {
  if (suppressTaxpayerWatch) return;
  if (!canLoad.value) return;
  if (!selectedTaxpayer.value) return;
  try {
    await loadTaxpayerDynamics();
  } catch (_) {
    // handled in loadTaxpayerDynamics
  }
});

onMounted(async () => {
  document.addEventListener("click", onDocumentClick);
  try {
    await loadFilters();
    await loadOverview();
  } catch (e) {
    errorText.value = e?.message || "Ошибка инициализации аналитики";
  }
});
onBeforeUnmount(() => {
  document.removeEventListener("click", onDocumentClick);
  summaryDonutChart?.destroy();
  msbTrendChart?.destroy();
  okedTopChart?.destroy();
  taxpayerChart?.destroy();
  taxpayerKbkChart?.destroy();
});
</script>

<style scoped src="./analytics-view.css"></style>
