<script setup>
import { ref, computed } from 'vue'
import {
  Table2,
  BarChart3,
  Download,
  Link as LinkIcon,
  Check,
  ExternalLink,
} from 'lucide-vue-next'
import {
  state,
  exportCurrentCSV,
  filterValueLabel,
  attributeLabel,
  questionPicker,
  questionLink,
  followQueryLink,
  toggleSidebar,
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

// Pantalla de inicio: el rango de años disponible y los tres pasos.
const waveSpan = computed(() => {
  const years = state.waves.map((w) => Number(w.year)).filter(Boolean)
  if (!years.length) return ''
  return `${Math.min(...years)}–${Math.max(...years)}`
})
const steps = [
  {
    title: 'Elige una pregunta',
    text: 'Búscala por tema, palabra o código en el panel izquierdo.',
  },
  {
    title: 'Desglosa y filtra',
    text: 'Cruza por sexo, edad, municipio o cualquier otra pregunta, y compara entre años.',
  },
  {
    title: 'Ejecuta y descarga',
    text: 'Mira la tabla o la gráfica, copia el enlace o baja el CSV.',
  },
]

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
      class="sticky top-0 z-10 -mx-4 -mt-4 mb-3.5 md:-mx-8 md:-mt-8 md:mb-7.5 h-0.5 overflow-hidden bg-brand/15"
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

    <!-- Inicio: qué es esto y cómo se usa -->
    <div v-else-if="!state.lastResult" class="h-full">
      <div class="max-w-225 mx-auto py-2 md:py-6">
        <div class="mb-8 md:mb-10">
          <p
            class="text-[11px] font-semibold uppercase tracking-wider text-brand mb-2"
          >
            Encuesta Así Vamos<template v-if="waveSpan">
              · {{ waveSpan }}</template
            >
          </p>
          <h1
            class="text-[26px] md:text-[34px] leading-[1.15] font-bold text-ink mb-3"
          >
            Explora qué opina Nuevo León
          </h1>
          <button
            @click="toggleSidebar"
            class="md:hidden mt-4 inline-flex items-center gap-2 bg-brand hover:bg-brand-dark text-white rounded-full px-5 py-2.5 text-sm font-bold shadow-lg shadow-brand/20 transition-colors"
          >
            Empezar una consulta
          </button>
        </div>

        <div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
          <div
            v-for="(s, i) in steps"
            :key="s.title"
            class="bg-white rounded-3xl border border-line p-5"
          >
            <span
              class="size-8 rounded-full bg-yellow text-ink text-sm font-bold flex items-center justify-center mb-3"
              >{{ i + 1 }}</span
            >
            <h3 class="font-semibold text-ink mb-1">{{ s.title }}</h3>
            <p class="text-sm text-muted leading-relaxed">{{ s.text }}</p>
          </div>
        </div>

        <div class="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
          <div class="bg-white rounded-3xl border border-line p-5">
            <h3 class="font-semibold text-ink mb-1.5">Sobre los datos</h3>
            <p class="text-sm text-muted leading-relaxed">
              Los datos provienen de la Encuesta Así Vamos, que
              <a
                href="https://comovamosnl.org/"
                target="_blank"
                rel="noopener"
                class="font-medium text-brand underline underline-offset-2"
                >Cómo Vamos Nuevo León</a
              >
              levanta cada año desde 2016 en colaboración con la UANL.
            </p>
          </div>
          <div class="bg-white rounded-3xl border border-line p-5">
            <h3 class="font-semibold text-ink mb-1.5">Metodología</h3>
            <p class="text-sm text-muted leading-relaxed">
              Encuesta probabilística con muestreo estratificado por nivel
              socioeconómico, edad y zona geográfica. Los resultados se
              proyectan a la población con el factor de expansión oficial.
            </p>
          </div>
        </div>

        <div
          class="bg-brand rounded-3xl p-6 md:p-8 text-white flex flex-col md:flex-row md:items-center gap-4 md:gap-8"
        >
          <div class="flex-1">
            <h3 class="font-bold text-lg md:text-xl mb-1">
              ¿Necesitas la base de datos completa?
            </h3>
            <p class="text-sm text-white/85 leading-relaxed">
              Los microdatos de la encuesta están en el sitio de Cómo Vamos
              Nuevo León.
            </p>
          </div>
          <a
            href="https://comovamosnl.org/encuesta-asi-vamos/"
            target="_blank"
            rel="noopener"
            class="shrink-0 inline-flex items-center justify-center gap-2 bg-yellow hover:bg-[#ffc933] text-ink font-bold rounded-full px-5 py-2.5 text-sm transition-colors"
          >
            Descargar base de datos
            <ExternalLink class="size-4" />
          </a>
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
          class="bg-white rounded-2xl border border-line shadow-sm overflow-hidden"
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
                class="flex items-center gap-2 py-1.5 px-3 border border-line rounded-full hover:bg-surface-soft transition-colors"
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
                class="flex items-center gap-2 py-1.5 px-3 border border-line rounded-full hover:bg-surface-soft transition-colors disabled:opacity-40 disabled:cursor-not-allowed shrink-0"
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
          class="bg-white border border-line rounded-2xl text-sm overflow-hidden"
        >
          <!-- En el teléfono la barra superior recorta la pregunta: aquí va
               completa. -->
          <p
            class="md:hidden px-5 pt-3 text-sm font-medium text-ink leading-snug"
          >
            {{ state.lastResult.question.q_text }}
          </p>
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
