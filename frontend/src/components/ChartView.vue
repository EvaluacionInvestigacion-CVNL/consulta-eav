<script setup>
import { ref, computed, watch, onBeforeUnmount, nextTick } from 'vue'
import { Chart, registerables } from 'chart.js'
import { PieChart, ChevronDown } from 'lucide-vue-next'

Chart.register(...registerables)

const props = defineProps({
  data: { type: Object, required: true },
  active: { type: Boolean, default: false },
})

const canvasEl = ref(null)
const pieCanvases = ref([])
let chartInstance = null
let pieInstances = []

const showPieCharts = ref(false)

// Numéricas en pivote: la distribución cruda es un dataset POR VALOR distinto,
// así que sólo se puede leer en escalas cortas (1-10, conteos chicos). Contando
// centinelas esas escalas llegan a ~13-15 valores; arriba de ahí (edad, tiempos,
// gastos) serían decenas de segmentos apilados y la única gráfica legible es la
// de promedios. 'promedio' | 'distribucion'.
const DIST_MAX_VALUES = 15
const numericMode = ref('promedio')

function setPieRef(el, i) {
  if (el) pieCanvases.value[i] = el
}

const FLAT_COLORS = [
  '#29c19b',
  '#7e33c3',
  '#ffba00',
  '#fb7e50',
  '#1f9778',
  '#5d2691',
  '#cc9500',
]
const PIVOT_COLORS = [
  '#29c19b',
  '#7e33c3',
  '#ffba00',
  '#fb7e50',
  '#1f9778',
  '#5d2691',
  '#cc9500',
  '#cc6540',
  '#5feaba',
  '#ad6ce0',
  '#ffd266',
  '#fda58a',
  '#7fdcc3',
  '#c094e0',
]

const isNumericPivot = computed(
  () =>
    props.data?.format === 'pivot' &&
    props.data.question?.q_type === 'numerica',
)

// Valores distintos de la numérica (las filas de datos del pivote, sin "Total").
const distinctValueCount = computed(
  () =>
    (props.data?.percentages?.rows || []).filter((r) => r[0] !== 'Total')
      .length,
)

const canShowDistribution = computed(
  () => !isNumericPivot.value || distinctValueCount.value <= DIST_MAX_VALUES,
)

const pieGroupLabels = computed(() => {
  if (!props.data || props.data.format !== 'pivot') return []
  // Las pies desglosan la distribución por columna, así que no aplican cuando la
  // gráfica principal son promedios.
  if (isNumericPivot.value && numericMode.value !== 'distribucion') return []
  const cols = props.data.percentages?.columns || []
  // Vista Año: 1 columna de etiqueta y sin "Total" final. Otros pivotes: 2 + Total.
  const year = props.data.group_by === 'year'
  return year ? cols.slice(1) : cols.slice(2, -1)
})

function destroyMain() {
  if (chartInstance) {
    chartInstance.destroy()
    chartInstance = null
  }
}

function destroyPies() {
  for (const c of pieInstances) c.destroy()
  pieInstances = []
}

function buildFlat(data) {
  const isNumerica = data.question.q_type === 'numerica'
  const labelIdx = isNumerica ? 0 : 1
  return {
    type: 'bar',
    data: {
      labels: data.rows.map((r) => r[labelIdx]),
      datasets: [
        {
          label: '%',
          data: data.rows.map((r) => r[r.length - 1]),
          backgroundColor: FLAT_COLORS.map((c) => c + 'CC'),
          borderColor: FLAT_COLORS,
          borderWidth: 1,
          borderRadius: 3,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: {
          grid: { display: false },
          ticks: { font: { family: 'Rubik', size: 11 } },
        },
        y: {
          grid: { color: 'rgba(0,0,0,0.05)' },
          ticks: {
            font: { family: 'Rubik', size: 11 },
            callback: (v) => v + '%',
          },
        },
      },
    },
  }
}

function buildPivot(data) {
  const year = data.group_by === 'year'
  const labelCols = year ? 1 : 2
  const cols = data.percentages.columns
  const rows = data.percentages.rows.filter((r) => r[0] !== 'Total')
  // La vista Año no lleva columna "Total" final; los demás pivotes sí.
  const groupLabels = year ? cols.slice(labelCols) : cols.slice(labelCols, -1)
  const groupRange = groupLabels.map((_, i) => i + labelCols)

  const datasets = rows.map((row, ri) => {
    const label = year
      ? String(row[0])
      : row[1] !== '' && row[1] != null
        ? String(row[1])
        : String(row[0])
    return {
      label,
      data: groupRange.map((i) => Number(row[i]) || 0),
      backgroundColor: PIVOT_COLORS[ri % PIVOT_COLORS.length] + 'CC',
      borderColor: PIVOT_COLORS[ri % PIVOT_COLORS.length],
      borderWidth: 1,
    }
  })

  return {
    type: 'bar',
    data: { labels: groupLabels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          position: 'bottom',
          labels: { font: { family: 'Rubik', size: 11 }, boxWidth: 12 },
        },
        tooltip: {
          callbacks: {
            label: (ctx) => `${ctx.dataset.label}: ${ctx.parsed.y}%`,
          },
        },
      },
      scales: {
        x: {
          stacked: true,
          grid: { display: false },
          ticks: {
            font: { family: 'Rubik', size: 10 },
            autoSkip: false,
            maxRotation: 60,
            minRotation: 30,
          },
        },
        y: {
          stacked: true,
          max: 100,
          grid: { color: 'rgba(0,0,0,0.05)' },
          ticks: {
            font: { family: 'Rubik', size: 11 },
            callback: (v) => v + '%',
          },
        },
      },
    },
  }
}

// Promedio por grupo.
function buildNumericMeans(data) {
  const year = data.group_by === 'year'
  const labelCols = year ? 1 : 2
  const cols = data.counts.columns
  const rows = data.counts.rows
  const avgRow = rows.find((r) => String(r[0]).startsWith('Promedio'))
  // Base para el tooltip.
  const baseRow =
    rows.find((r) => String(r[0]).startsWith('Base')) ||
    rows.find((r) => r[0] === 'Total')
  // La vista Año no lleva columna "Total" final; los demás pivotes sí.
  const groupLabels = year ? cols.slice(labelCols) : cols.slice(labelCols, -1)
  const groupRange = groupLabels.map((_, i) => i + labelCols)

  // Celda vacía = ese grupo no tiene promedio.
  const values = groupRange.map((i) => {
    const raw = avgRow?.[i]
    if (raw === '' || raw == null) return null
    const v = Number(raw)
    return Number.isFinite(v) ? v : null
  })
  const bases = groupRange.map((i) => Number(baseRow?.[i]) || 0)

  return {
    type: 'bar',
    data: {
      labels: groupLabels,
      datasets: [
        {
          label: 'Promedio',
          data: values,
          backgroundColor: FLAT_COLORS[0] + 'CC',
          borderColor: FLAT_COLORS[0],
          borderWidth: 1,
          borderRadius: 3,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            // La base va en el tooltip.
            label: (ctx) => {
              const n = bases[ctx.dataIndex]
              const base = n ? ` · base ${n.toLocaleString('en-US')}` : ''
              return `Promedio: ${ctx.parsed.y}${base}`
            },
          },
        },
      },
      scales: {
        x: {
          grid: { display: false },
          ticks: {
            font: { family: 'Rubik', size: 10 },
            autoSkip: false,
            maxRotation: 60,
            minRotation: 30,
          },
        },
        y: {
          beginAtZero: true,
          grid: { color: 'rgba(0,0,0,0.05)' },
          ticks: { font: { family: 'Rubik', size: 11 } },
        },
      },
    },
  }
}

function buildPie(data, groupIdx) {
  const year = data.group_by === 'year'
  const labelCols = year ? 1 : 2
  const colIdx = groupIdx + labelCols
  const rows = data.percentages.rows.filter((r) => r[0] !== 'Total')
  const labels = []
  const values = []
  const bg = []
  const bd = []
  rows.forEach((row, ri) => {
    const v = Number(row[colIdx]) || 0
    if (v <= 0) return
    const label = year
      ? String(row[0])
      : row[1] !== '' && row[1] != null
        ? String(row[1])
        : String(row[0])
    labels.push(label)
    values.push(v)
    bg.push(PIVOT_COLORS[ri % PIVOT_COLORS.length] + 'CC')
    bd.push(PIVOT_COLORS[ri % PIVOT_COLORS.length])
  })
  return {
    type: 'pie',
    data: {
      labels,
      datasets: [
        {
          data: values,
          backgroundColor: bg,
          borderColor: '#fff',
          borderWidth: 1,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          position: 'bottom',
          labels: {
            font: { family: 'Rubik', size: 10 },
            boxWidth: 10,
            padding: 8,
          },
        },
        tooltip: {
          callbacks: { label: (ctx) => `${ctx.label}: ${ctx.parsed}%` },
        },
      },
    },
  }
}

function buildConfig(data) {
  if (isNumericPivot.value && numericMode.value === 'promedio')
    return buildNumericMeans(data)
  return data.format === 'pivot' ? buildPivot(data) : buildFlat(data)
}

// `renderToken` descarta los renders que quedaron obsoletos durante el
// `nextTick`: sin él, dos disparos seguidos (cambio de datos + cambio de modo)
// pasan ambos el await y el segundo `new Chart` truena sobre un canvas ocupado.
let renderToken = 0

async function renderMain() {
  destroyMain()
  if (!props.data || !props.active) return
  const token = ++renderToken
  await nextTick()
  if (token !== renderToken || !canvasEl.value) return
  chartInstance = new Chart(canvasEl.value, buildConfig(props.data))
}

async function renderPies() {
  destroyPies()
  if (!props.data || !props.active) return
  if (props.data.format !== 'pivot' || !showPieCharts.value) return
  await nextTick()
  const count = pieGroupLabels.value.length
  for (let i = 0; i < count; i++) {
    const el = pieCanvases.value[i]
    if (!el) continue
    pieInstances.push(new Chart(el, buildPie(props.data, i)))
  }
}

watch(
  () => [props.data, props.active],
  () => {
    showPieCharts.value = false
    numericMode.value = 'promedio'
    renderMain()
    destroyPies()
  },
  { immediate: true },
)

watch(numericMode, () => {
  showPieCharts.value = false
  destroyPies()
  renderMain()
})

watch(showPieCharts, renderPies)

onBeforeUnmount(() => {
  destroyMain()
  destroyPies()
})
</script>

<template>
  <div class="space-y-8">
    <div>
      <div class="flex items-center justify-between mb-3 px-2 gap-4">
        <h3 class="text-sm font-bold text-ink">Resultados</h3>
        <!-- El toggle sólo aparece cuando la distribución es menor a DIST_MAX_VALUES -->
        <div
          v-if="isNumericPivot && canShowDistribution"
          class="flex gap-1 bg-surface p-1 rounded-2xl shrink-0"
        >
          <button
            @click="numericMode = 'promedio'"
            class="px-3 py-1 rounded-xl text-xs font-bold transition-colors"
            :class="
              numericMode === 'promedio'
                ? 'bg-white text-brand shadow-sm'
                : 'text-faint hover:text-muted'
            "
          >
            Promedio
          </button>
          <button
            @click="numericMode = 'distribucion'"
            class="px-3 py-1 rounded-xl text-xs font-bold transition-colors"
            :class="
              numericMode === 'distribucion'
                ? 'bg-white text-brand shadow-sm'
                : 'text-faint hover:text-muted'
            "
          >
            Distribución
          </button>
        </div>
      </div>

      <div class="relative h-80">
        <canvas ref="canvasEl"></canvas>
      </div>
    </div>

    <div v-if="pieGroupLabels.length" class="space-y-4">
      <button
        @click="showPieCharts = !showPieCharts"
        class="flex items-center gap-2 text-sm font-semibold text-brand hover:text-brand-dark transition-colors"
      >
        <PieChart class="size-4" />
        {{ showPieCharts ? 'Ocultar' : 'Mostrar' }} distribución por columna
        <ChevronDown
          class="size-4 transition-transform"
          :class="showPieCharts ? 'rotate-180' : ''"
        />
      </button>

      <div v-if="showPieCharts" class="grid grid-cols-2 lg:grid-cols-3 gap-6">
        <div
          v-for="(label, i) in pieGroupLabels"
          :key="label"
          class="bg-white border border-gray-300 rounded-lg p-4"
        >
          <p
            class="text-xs font-bold text-muted uppercase tracking-wider mb-2 text-center"
          >
            {{ label }}
          </p>
          <div class="relative h-60">
            <canvas :ref="(el) => setPieRef(el, i)"></canvas>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
