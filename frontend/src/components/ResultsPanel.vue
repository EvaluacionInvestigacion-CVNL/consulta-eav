<script setup>
import { ref, computed } from 'vue'
import {
  Table2,
  BarChart3,
  Download,
  Link as LinkIcon,
  Check,
} from 'lucide-vue-next'
import {
  state,
  exportCurrentCSV,
  filterValueLabel,
  attributeLabel,
  questionPicker,
  questionLink,
  followQueryLink,
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

// Las otras preguntas del mismo bloque (p. ej. los incisos de una batería).
const blockSiblings = computed(() => {
  const qid = state.lastResult?.question?.q_id
  const groupId = qid && questionPicker.value.groupOf.get(qid)
  if (!groupId) return []
  return [...questionPicker.value.byId.values()].filter(
    (m) => m.groupId === groupId && m.id !== qid,
  )
})

// Al seguir un link (están al fondo) se sube al inicio del resultado. Un clic
// con Ctrl/Cmd/Shift abre otra pestaña: ahí no se mueve nada.
const scroller = ref(null)
function openLink(event, href) {
  if (
    !(event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0)
  ) {
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    scroller.value?.scrollTo({ top: 0, behavior: reduce ? 'auto' : 'smooth' })
  }
  followQueryLink(event, href)
}

const linkCopied = ref(false)
async function copyLink() {
  await navigator.clipboard.writeText(location.href)
  linkCopied.value = true
  setTimeout(() => (linkCopied.value = false), 1500)
}
const appliedFilters = computed(() => state.lastResult?.filters_applied ?? [])
const fmtNum = (n) => (n == null ? '—' : Number(n).toLocaleString('es-MX'))
const groupByLabel = computed(() => {
  const g = state.lastResult?.group_by
  if (!g || g === 'answer') return 'Respuesta'
  if (g === 'year') return 'Año'
  if (g === 'city_id') return 'Ciudad'
  const attr = state.attributes.find((a) => a.attribute === g)
  if (attr) return attr.label || attr.attribute
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
  <div ref="scroller" class="flex-1 overflow-auto p-4 md:p-8 bg-cream">
    <!-- Cargando con un resultado en pantalla: barra delgada arriba, sin
         sustituir el resultado (que se atenúa). La altura neta es 0 para que
         nada salte. -->
    <div
      v-if="state.loading && state.lastResult"
      class="sticky top-0 z-10 -mx-4 -mt-4 mb-[calc(1rem-2px)] md:-mx-8 md:-mt-8 md:mb-[calc(2rem-2px)] h-0.5 overflow-hidden bg-brand/15"
    >
      <div class="progress-bar h-full w-1/3 bg-brand"></div>
    </div>

    <!-- Loading (primera consulta: no hay resultado que mostrar) -->
    <div
      v-if="state.loading && !state.lastResult"
      class="flex items-center justify-center h-full gap-2.5 text-muted"
    >
      <div class="spinner"></div>
      Consultando…
    </div>

    <!-- Error -->
    <div
      v-else-if="state.error"
      class="flex flex-col items-center justify-center h-full text-faint text-center gap-3"
    >
      <div class="text-[42px]">⚠</div>
      <div class="font-semibold text-lg text-ink">Error al consultar</div>
      <div class="text-sm">{{ state.error }}</div>
    </div>

    <!-- Empty -->
    <div
      v-else-if="!state.lastResult"
      class="flex flex-col items-center justify-center h-full text-faint text-center gap-3"
    >
      <div class="flex-1 overflow-auto p-4 md:p-8">
        <div class="max-w-225 mx-auto">
          <div class="grid grid-cols-1 md:grid-cols-2 gap-6 mb-8">
            <div class="bg-white rounded-lg border border-line p-6">
              <div class="flex items-start gap-4">
                <!-- <div class="bg-brand/10 rounded-lg p-3 shrink-0">
                  <svg
                    class="size-6 text-brand"
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
                  <h3 class="font-semibold text-ink mb-2">Sobre los Datos</h3>
                  <p class="text-sm text-muted leading-relaxed mb-3">
                    Los datos provienen de la Encuesta Así Vamos realizada
                    anualmente de 2016 a 2025 por
                    <a href="https://comovamosnl.org/" target="_blank">
                      <span class="font-medium underline text-brand">
                        Cómo Vamos Nuevo León</span
                      >
                    </a>
                    en colaboración con la UANL.
                  </p>
                </div>
              </div>
            </div>

            <div class="bg-white rounded-lg border border-line p-6">
              <div class="flex items-start gap-4">
                <!-- <div class="bg-brand/10 rounded-lg p-3 shrink-0">
                  <svg
                    class="size-6 text-brand"
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
                  <h3 class="font-semibold text-ink mb-2">Metodología</h3>
                  <p class="text-sm text-muted leading-relaxed mb-3">
                    Encuestas aplicadas mediante metodología probabilística con
                    muestreo estratificado por nivel socioeconómico, edad y zona
                    geográfica.
                  </p>
                </div>
              </div>
            </div>
          </div>

          <div class="bg-brand rounded-lg p-5 md:p-8 text-white">
            <div class="flex items-start justify-between">
              <div class="flex-1">
                <h3 class="font-bold text-xl mb-2">
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
                      class="bg-white text-ink-soft px-4 py-2 rounded-lg font-medium hover:bg-white/90 hover:cursor-pointer transition-colors text-sm"
                    >
                      Descargar base de datos
                    </button>
                  </a>
                </div>
              </div>
            </div>
          </div>

          <div
            class="mt-8 bg-orange rounded-4xl p-6 border border-line text-center"
          >
            <h3
              class="font-extrabold text-yellow text-lg mb-3 flex items-center justify-center gap-2"
            >
              ¿CÓMO USAR ESTA HERRAMIENTA?
            </h3>
            <ol class="space-y-2 text-sm text-ink-soft">
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

    <!-- Results: el anterior se atenúa mientras carga y el nuevo entra con
         un fundido corto (sólo entrada, para no tener dos a la vez). -->
    <Transition
      v-else
      enter-active-class="motion-safe:transition-opacity motion-safe:duration-200"
      enter-from-class="opacity-0"
    >
      <div
        :key="state.resultVersion"
        class="max-w-7xl mx-auto space-y-8 motion-safe:transition-opacity motion-safe:duration-150"
        :class="state.loading ? 'opacity-50 pointer-events-none' : ''"
      >
        <!-- Data Visualization Card -->
        <div
          class="bg-white rounded-lg border border-line shadow-sm overflow-hidden"
        >
          <div
            class="border-b border-surface px-3 md:px-6 py-3 flex flex-wrap items-center justify-between gap-2"
          >
            <div class="flex gap-4 md:gap-8">
              <button
                @click="setTab('table')"
                class="flex items-center gap-2 pb-3 border-b-2 transition-colors"
                :class="
                  state.activeTab === 'table'
                    ? 'border-brand text-brand'
                    : 'border-transparent text-faint'
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
                    ? 'border-brand text-brand'
                    : 'border-transparent text-faint'
                "
              >
                <BarChart3 class="size-3.5" />
                <span class="font-bold text-sm">Gráfica</span>
              </button>
            </div>
            <div class="flex items-center gap-2 shrink-0">
              <button
                @click="copyLink"
                class="flex items-center gap-2 py-1.5 px-2 border border-line rounded hover:bg-surface-soft transition-colors"
              >
                <Check v-if="linkCopied" class="size-3.5 text-brand" />
                <LinkIcon v-else class="size-3.5 text-ink-soft" />
                <span class="font-semibold text-sm text-ink-soft">{{
                  linkCopied ? 'Copiado' : 'Copiar enlace'
                }}</span>
              </button>
              <button
                @click="exportCurrentCSV"
                :disabled="exportDisabled"
                class="flex items-center gap-2 py-1.5 px-2 border border-line rounded hover:bg-surface-soft transition-colors disabled:opacity-40 disabled:cursor-not-allowed shrink-0"
              >
                <Download class="size-3.5 text-ink-soft" />
                <span class="font-semibold text-sm text-ink-soft"
                  >Descargar CSV</span
                >
              </button>
            </div>
          </div>

          <div
            v-show="state.activeTab === 'table'"
            class="p-3 md:p-6 space-y-8"
          >
            <PivotTables v-if="isPivot" :data="state.lastResult" />
            <DataTable v-else :data="state.lastResult" />
          </div>
          <div v-show="state.activeTab === 'chart'" class="p-3 md:p-8">
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
          class="bg-white border border-line rounded-lg text-sm overflow-hidden"
        >
          <div class="px-5 py-3 flex flex-wrap items-center gap-x-4 gap-y-2">
            <!-- Pregunta -->
            <span class="inline-flex items-center gap-2">
              <span
                class="font-mono text-xs bg-brand-soft text-brand px-2 py-0.5 rounded font-bold"
                >{{ state.lastResult.question.q_id }}</span
              >
              <span class="text-muted">{{
                state.lastResult.question.q_type
              }}</span>
            </span>

            <span class="w-px h-4 bg-line"></span>

            <!-- Año / comparación -->
            <span v-if="!isYear">
              <span class="text-faint">Año</span>
              <span class="font-semibold text-ink-soft ml-1">{{
                state.lastResult.wave_id ?? '—'
              }}</span>
            </span>
            <span v-else class="font-semibold text-ink-soft"
              >Comparación por año</span
            >

            <span class="w-px h-4 bg-line"></span>

            <!-- Agrupación -->
            <span>
              <span class="text-faint">Agrupado por</span>
              <span class="font-semibold text-ink-soft ml-1">{{
                groupByLabel
              }}</span>
            </span>

            <span class="w-px h-4 bg-line"></span>

            <!-- Universo -->
            <span v-if="!isYear">
              <span class="text-faint">Universo</span>
              <span class="font-semibold text-ink-soft ml-1"
                >{{ totalRespondents }} personas</span
              >
            </span>
            <span
              v-else
              class="inline-flex flex-wrap items-center gap-x-2 gap-y-1"
            >
              <span class="text-faint">Universo por año</span>
              <span
                v-for="yb in yearBases"
                :key="yb.year"
                class="font-semibold text-ink-soft"
              >
                <span class="text-muted font-normal">{{ yb.year }}:</span>
                {{ fmtNum(yb.base) }}
              </span>
            </span>

            <!-- Filtros -->
            <template v-if="appliedFilters.length">
              <span class="w-px h-4 bg-line"></span>
              <span class="inline-flex flex-wrap items-center gap-1.5">
                <span class="text-faint">Filtros</span>
                <span
                  v-for="(f, i) in appliedFilters"
                  :key="i"
                  class="bg-brand-soft text-brand text-xs font-medium px-2 py-0.5 rounded"
                >
                  {{ f.question ?? attributeLabel(f.attribute) }}:
                  {{ filterValueLabel(f) }}
                </span>
              </span>
            </template>
          </div>

          <!-- Cómo se preguntó cada año. Fuera de la vista Año son links a las
               otras versiones; las que no se comparan dicen por qué. -->
          <div
            v-if="yearTexts.length"
            class="border-t border-surface px-5 py-3"
          >
            <h4
              class="text-xs font-bold text-muted uppercase tracking-wide mb-2"
            >
              {{
                isYear
                  ? 'Cómo se preguntó cada año'
                  : 'Esta pregunta en otros años'
              }}
            </h4>
            <p v-if="yearTexts.length === 1" class="text-ink-soft">
              Sólo se preguntó en {{ yearTexts[0].year }}.
            </p>
            <ul v-else class="space-y-1">
              <li
                v-for="t in yearTexts"
                :key="t.year"
                class="text-ink-soft flex gap-2"
              >
                <span class="font-semibold text-ink shrink-0">{{
                  t.year
                }}</span>
                <span
                  v-if="!isYear && t.year === state.lastResult.wave_id"
                  class="shrink-0 font-mono text-xs text-muted bg-surface rounded px-1.5 py-0.5 self-start"
                  :title="'La que estás viendo'"
                  >{{ t.q_id }}</span
                >
                <a
                  v-else-if="t.q_id"
                  :href="questionLink(t.q_id, { w: t.year, keepCut: false })"
                  @click="
                    openLink(
                      $event,
                      questionLink(t.q_id, { w: t.year, keepCut: false }),
                    )
                  "
                  :title="`Abrir ${t.q_id} en ${t.year}`"
                  :class="[
                    'shrink-0 font-mono text-xs rounded px-1.5 py-0.5 self-start hover:underline',
                    t.comparable === false
                      ? 'text-muted bg-surface'
                      : 'text-brand bg-brand-soft',
                  ]"
                  >{{ t.q_id }}</a
                >
                <span :class="t.comparable === false ? 'text-faint' : ''">
                  {{ t.q_text }}
                  <span
                    v-if="t.comparable === false"
                    class="ml-1 inline-block text-[11px] font-semibold text-warn-ink bg-warn-soft rounded px-1.5 py-0.5"
                    >No comparable: {{ t.reason_label }}</span
                  >
                </span>
              </li>
            </ul>
          </div>

          <!-- Preguntas del mismo bloque: links que conservan el corte actual -->
          <div
            v-if="blockSiblings.length"
            class="border-t border-surface px-5 py-3"
          >
            <h4
              class="text-xs font-bold text-muted uppercase tracking-wide mb-2"
            >
              Del mismo bloque
              <span class="normal-case font-normal text-faint"
                >· {{ blockSiblings[0].block }}</span
              >
            </h4>
            <div class="flex flex-wrap gap-1.5">
              <a
                v-for="m in blockSiblings"
                :key="m.id"
                :href="questionLink(m.id)"
                @click="openLink($event, questionLink(m.id))"
                class="inline-flex items-center gap-1.5 max-w-full border border-line rounded-full px-2.5 py-1 text-xs text-ink-soft hover:border-brand transition-colors"
              >
                <span class="font-mono text-brand">{{ m.id }}</span>
                <span class="truncate">{{ m.main }}</span>
              </a>
            </div>
          </div>
        </div>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.progress-bar {
  animation: progress 1.1s ease-in-out infinite;
}
@keyframes progress {
  from {
    transform: translateX(-100%);
  }
  to {
    transform: translateX(300%);
  }
}
@media (prefers-reduced-motion: reduce) {
  .progress-bar {
    animation: none;
    width: 100%;
  }
}
</style>
