<script setup>
import { computed } from 'vue'
import { Table2, BarChart3, Download } from 'lucide-vue-next'
import {
  state,
  exportCurrentCSV,
  filterValueLabel,
  attributeLabel,
  questionPicker,
} from '../store.js'
import DataTable from './DataTable.vue'
import PivotTables from './PivotTables.vue'
import ChartView from './ChartView.vue'

const isPivot = computed(() => state.lastResult?.format === 'pivot')
const exportDisabled = computed(() => !state.lastResult || state.loading)
const totalRespondents = computed(
  () => state.lastResult?.total_respondents?.toLocaleString('es-MX') ?? '—',
)
const isYear = computed(() => state.lastResult?.group_by === 'year')
const yearBases = computed(() => state.lastResult?.year_bases ?? [])
const yearTexts = computed(() => state.lastResult?.year_texts ?? [])
const appliedFilters = computed(() => state.lastResult?.filters_applied ?? [])
const fmtNum = (n) => (n == null ? '—' : Number(n).toLocaleString('es-MX'))
const groupByLabel = computed(() => {
  const g = state.lastResult?.group_by
  if (!g || g === 'answer') return 'Respuesta'
  if (g === 'year') return 'Año'
  if (g === 'city_id') return 'Ciudad'
  const attr = state.attributes.find((a) => a.attribute === g)
  if (attr) return attr.label || attr.attribute
  const recode = state.recodes.find((r) => r.key === g)
  if (recode) return recode.label
  // Cross-tab by another question: show its code + text, not the raw q_id.
  const q = questionPicker.value.byId.get(g)
  if (q) return `${q.id} · ${q.main}`
  return g
})

function setTab(t) {
  state.activeTab = t
}
</script>

<template>
  <div class="flex-1 overflow-auto p-8 bg-[#fcf0e4]">
    <!-- Loading -->
    <div
      v-if="state.loading"
      class="flex items-center justify-center h-full gap-2.5 text-[#64748b]"
    >
      <div class="spinner"></div>
      Consultando…
    </div>

    <!-- Error -->
    <div
      v-else-if="state.error"
      class="flex flex-col items-center justify-center h-full text-[#94a3b8] text-center gap-3"
    >
      <div class="text-[42px]">⚠</div>
      <div class="font-['Manrope'] font-semibold text-lg text-[#1e293b]">
        Error al consultar
      </div>
      <div class="text-sm">{{ state.error }}</div>
    </div>

    <!-- Empty -->
    <div
      v-else-if="!state.lastResult"
      class="flex flex-col items-center justify-center h-full text-[#94a3b8] text-center gap-3"
    >
      <div class="flex-1 overflow-auto p-8">
        <div class="max-w-225 mx-auto">
          <div class="grid grid-cols-2 gap-6 mb-8">
            <div class="bg-white rounded-lg border border-[#e2e8f0] p-6">
              <div class="flex items-start gap-4">
                <!-- <div class="bg-[#0d9488]/10 rounded-lg p-3 shrink-0">
                  <svg
                    class="size-6 text-[#0d9488]"
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                  >
                    <path
                      stroke-linecap="round"
                      stroke-linejoin="round"
                      stroke-width="2"
                      d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
                    />
                  </svg>
                </div> -->
                <div>
                  <h3 class="font-semibold text-[#1e293b] mb-2">
                    Sobre los Datos
                  </h3>
                  <p class="text-sm text-[#64748b] leading-relaxed mb-3">
                    Los datos provienen de la Encuesta Así Vamos realizada
                    anualmente de 2016 a 2025 por
                    <a href="https://comovamosnl.org/" target="_blank">
                      <span class="font-medium underline text-[#0d9488]">
                        Cómo Vamos Nuevo León</span
                      >
                    </a>
                    en colaboración con la UANL.
                  </p>
                </div>
              </div>
            </div>

            <div class="bg-white rounded-lg border border-[#e2e8f0] p-6">
              <div class="flex items-start gap-4">
                <!-- <div class="bg-[#0d9488]/10 rounded-lg p-3 shrink-0">
                  <svg
                    class="size-6 text-[#0d9488]"
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                  >
                    <path
                      stroke-linecap="round"
                      stroke-linejoin="round"
                      stroke-width="2"
                      d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-3 7h3m-3 4h3m-6-4h.01M9 16h.01"
                    />
                  </svg>
                </div> -->
                <div>
                  <h3 class="font-semibold text-[#1e293b] mb-2">Metodología</h3>
                  <p class="text-sm text-[#64748b] leading-relaxed mb-3">
                    Encuestas aplicadas mediante metodología probabilística con
                    muestreo estratificado por nivel socioeconómico, edad y zona
                    geográfica.
                  </p>
                </div>
              </div>
            </div>
          </div>

          <div class="bg-[#7e34c3] rounded-lg p-8 text-white">
            <div class="flex items-start justify-between">
              <div class="flex-1">
                <h3 class="font-['Manrope'] font-bold text-xl mb-2">
                  Acceso a Base de Datos Completa
                </h3>
                <div class="w-full justify-center">
                  <p class="text-white/90 mb-4 text-center">
                    ¿Necesitas acceso a los datos en bruto o realizar análisis
                    personalizados? Aquí puedes descargar la base de datos.
                  </p>
                </div>
                <div class="flex gap-3 justify-center">
                  <a
                    href="https://comovamosnl.org/encuesta-asi-vamos/"
                    target="_blank"
                  >
                    <button
                      class="bg-white text-[#303030] px-4 py-2 rounded-lg font-medium hover:bg-white/90 hover:cursor-pointer transition-colors text-sm"
                    >
                      Descargar BD
                    </button>
                  </a>
                </div>
              </div>
            </div>
          </div>

          <div
            class="mt-8 bg-[#fb7e50] rounded-4xl p-6 border border-[#e2e8f0] font-['Poppins'] text-center"
          >
            <h3
              class="font-['Poppins'] font-extrabold text-[#ffba00] text-lg mb-3 flex items-center justify-center gap-2"
            >
              ¿CÓMO USAR ESTA HERRAMIENTA?
            </h3>
            <ol class="space-y-2 text-sm text-[#303030]">
              <li class="flex justify-center gap-3">
                <span
                  >Selecciona una pregunta de la encuesta en el panel
                  izquierdo</span
                >
              </li>
              <li class="flex justify-center gap-3">
                <span
                  >Elige cómo agrupar los resultados (por edad, zona, nivel
                  socioeconómico, etc.)</span
                >
              </li>
              <li class="flex justify-center gap-3">
                <span
                  >Haz clic en "Ejecutar consulta" para ver los resultados</span
                >
              </li>
              <li class="flex justify-center gap-3">
                <span
                  >Visualiza los datos en formato de tabla o gráfica y descarga
                  en CSV si lo necesitas</span
                >
              </li>
            </ol>
          </div>
        </div>
      </div>
    </div>

    <!-- Results -->
    <div v-else class="max-w-7xl mx-auto space-y-8">
      <!-- Data Visualization Card -->
      <div
        class="bg-white rounded-lg border border-[#e2e8f0] shadow-sm overflow-hidden"
      >
        <div
          class="border-b border-[#f1f5f9] px-6 py-3 flex items-center justify-between"
        >
          <div class="flex gap-8">
            <button
              @click="setTab('table')"
              class="flex items-center gap-2 pb-3 border-b-2 transition-colors"
              :class="
                state.activeTab === 'table'
                  ? 'border-[#0d9488] text-[#0d9488]'
                  : 'border-transparent text-[#94a3b8]'
              "
            >
              <Table2 class="size-3.5" />
              <span class="font-bold text-sm">Tabla</span>
            </button>
            <button
              @click="setTab('chart')"
              class="flex items-center gap-2 pb-3 border-b-2 transition-colors"
              :class="
                state.activeTab === 'chart'
                  ? 'border-[#0d9488] text-[#0d9488]'
                  : 'border-transparent text-[#94a3b8]'
              "
            >
              <BarChart3 class="size-3.5" />
              <span class="font-bold text-sm">Gráfica</span>
            </button>
          </div>
          <button
            @click="exportCurrentCSV"
            :disabled="exportDisabled"
            class="flex items-center gap-2 py-1.5 px-2 border border-[#e2e8f0] rounded hover:bg-[#f8fafc] transition-colors disabled:opacity-40 disabled:cursor-not-allowed shrink-0"
          >
            <Download class="size-3.5 text-[#475569]" />
            <span class="font-semibold text-sm text-[#475569]"
              >Descargar CSV</span
            >
          </button>
        </div>

        <div v-show="state.activeTab === 'table'" class="p-6 space-y-8">
          <PivotTables v-if="isPivot" :data="state.lastResult" />
          <DataTable v-else :data="state.lastResult" />
        </div>
        <div v-show="state.activeTab === 'chart'" class="p-8">
          <ChartView
            :data="state.lastResult"
            :active="state.activeTab === 'chart'"
          />
        </div>
      </div>

      <!-- Metadata de la consulta. Una sola tarjeta: la franja compacta y el
           redactado por año son lo mismo (contexto del resultado), así que van
           juntos y separados sólo por una divisoria interna. Vive aquí y no en
           PivotTables para que también se vea en la pestaña Gráfica. -->
      <div
        class="bg-white border border-[#e2e8f0] rounded-lg text-sm overflow-hidden"
      >
        <div class="px-5 py-3 flex flex-wrap items-center gap-x-4 gap-y-2">
          <!-- Pregunta -->
          <span class="inline-flex items-center gap-2">
            <span
              class="font-mono text-xs bg-[#f0fdfa] text-[#0d9488] px-2 py-0.5 rounded font-bold"
              >{{ state.lastResult.question.q_id }}</span
            >
            <span class="text-[#64748b]">{{
              state.lastResult.question.q_type
            }}</span>
          </span>

          <span class="w-px h-4 bg-[#e2e8f0]"></span>

          <!-- Año / comparación -->
          <span v-if="!isYear">
            <span class="text-[#94a3b8]">Año</span>
            <span class="font-semibold text-[#334155] ml-1">{{
              state.lastResult.wave_id ?? '—'
            }}</span>
          </span>
          <span v-else class="font-semibold text-[#334155]"
            >Comparación por año</span
          >

          <span class="w-px h-4 bg-[#e2e8f0]"></span>

          <!-- Agrupación -->
          <span>
            <span class="text-[#94a3b8]">Agrupado por</span>
            <span class="font-semibold text-[#334155] ml-1">{{
              groupByLabel
            }}</span>
          </span>

          <span class="w-px h-4 bg-[#e2e8f0]"></span>

          <!-- Universo -->
          <span v-if="!isYear">
            <span class="text-[#94a3b8]">Universo</span>
            <span class="font-semibold text-[#334155] ml-1"
              >{{ totalRespondents }} personas</span
            >
          </span>
          <span
            v-else
            class="inline-flex flex-wrap items-center gap-x-2 gap-y-1"
          >
            <span class="text-[#94a3b8]">Universo por año</span>
            <span
              v-for="yb in yearBases"
              :key="yb.year"
              class="font-semibold text-[#334155]"
            >
              <span class="text-[#64748b] font-normal">{{ yb.year }}:</span>
              {{ fmtNum(yb.base) }}
            </span>
          </span>

          <!-- Filtros -->
          <template v-if="appliedFilters.length">
            <span class="w-px h-4 bg-[#e2e8f0]"></span>
            <span class="inline-flex flex-wrap items-center gap-1.5">
              <span class="text-[#94a3b8]">Filtros</span>
              <span
                v-for="(f, i) in appliedFilters"
                :key="i"
                class="bg-[#f0fdfa] text-[#0d9488] text-xs font-medium px-2 py-0.5 rounded"
              >
                {{ f.question ?? attributeLabel(f.attribute) }}:
                {{ filterValueLabel(f) }}
              </span>
            </span>
          </template>
        </div>

        <!-- Cómo se preguntó cada año (sólo en la comparación por año) -->
        <div
          v-if="isYear && yearTexts.length"
          class="border-t border-[#f1f5f9] px-5 py-3"
        >
          <h4
            class="text-xs font-bold text-[#64748b] uppercase tracking-wide mb-2"
          >
            Cómo se preguntó cada año
          </h4>
          <ul class="space-y-1">
            <li
              v-for="t in yearTexts"
              :key="t.year"
              class="text-[#475569] flex gap-2"
            >
              <span class="font-semibold text-[#1e293b] shrink-0">{{
                t.year
              }}</span>
              <span
                v-if="t.q_id"
                class="shrink-0 font-mono text-xs text-[#0d9488] bg-[#f0fdfa] rounded px-1.5 py-0.5 self-start"
                >{{ t.q_id }}</span
              >
              <span>{{ t.q_text }}</span>
            </li>
          </ul>
        </div>
      </div>
    </div>
  </div>
</template>
