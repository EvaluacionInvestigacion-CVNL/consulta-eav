<script setup>
import { computed, ref } from 'vue'
import InfoTooltip from './InfoTooltip.vue'

const props = defineProps({
  data: { type: Object, required: true },
})

// Indica la presentación de la tabla (abs | pct).
const mode = ref('pct')

// Devuelve True si es agrupación por año
const isYear = computed(() => props.data.group_by === 'year')

// Columnas de respuestas: En año hay 1 (Respuesta), en los demás pivotes hay 2 (id_respuesta + Respuesta).
const labelCols = computed(() => (isYear.value ? 1 : 2))

const columns = computed(() => props.data.counts.columns)

// El código de la opción (id_respuesta) le sirve al equipo, no al lector: no se
// pinta. Los renglones "Total" y "Promedio" llevan su etiqueta en esa columna,
// así que ahí se muestra en la de Respuesta.
const hiddenCol = computed(() => columns.value.indexOf('id_respuesta'))
const visibleCols = computed(() =>
  columns.value.map((_, i) => i).filter((i) => i !== hiddenCol.value),
)
function cellAt(cells, ci) {
  const hidden = hiddenCol.value
  if (hidden >= 0 && ci === hidden + 1 && (cells[ci] ?? '') === '')
    return cells[hidden]
  return cells[ci]
}

// Obtener las filas de counts cuyos labels no existen en percentages (Promedio, Base ponderada).
const statRows = computed(() => {
  const percentageLabels = new Set(
    props.data.percentages.rows.map((row) => row[0]),
  )

  return props.data.counts.rows.filter((row) => !percentageLabels.has(row[0]))
})

const statLabels = computed(() => new Set(statRows.value.map((r) => r[0])))

// Filas a pintar con flag de stat.
const displayRows = computed(() => {
  const base =
    mode.value === 'abs' ? props.data.counts.rows : props.data.percentages.rows

  const out = base.map((cells) => ({
    cells,
    stat: statLabels.value.has(cells[0]),
  }))

  if (mode.value !== 'pct') return out

  for (const cells of statRows.value) {
    out.push({ cells, stat: true })
  }

  return out
})

// Minúsculas, sin acentos, sin puntuación y con espacios colapsados.
function normalizeLabel(label) {
  const key = label
    .normalize('NFD')
    .replace(/\p{Diacritic}/gu, '')
    .toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, ' ')
    .trim()

  return key || label.trim()
}

// Etiquetas distintas que tuvo esta opción a lo largo de los años, en orden de
// aparición. Se comparan normalizadas, pero se muestra la primera forma vista.
function distinctLabels(entry) {
  const seen = new Map()
  for (const v of Object.values(entry.years)) {
    if (!v || !v.label) continue
    const key = normalizeLabel(v.label)
    if (!seen.has(key)) seen.set(key, v.label)
  }
  return [...seen.values()]
}

// Tooltip de los distintos tipos de respuesta (ej. "Hombre | Masculino").
function rawTooltip(entry) {
  return distinctLabels(entry).join(' | ')
}

// Marcador en la columna Respuesta cuando la etiqueta varió entre años.
function diffEntry(ri, row, ci) {
  if (!isYear.value || ci !== 0 || isTotalRow(row)) return null
  const e = (props.data.year_option_map ?? [])[ri]
  return (e && distinctLabels(e).length) > 1 ? e : null
}

function isNumeric(cell, ci) {
  return ci >= labelCols.value
}

function isTotalRow(row) {
  return row[0] === 'Total'
}

function formatCount(cell, row, ci) {
  if (ci < labelCols.value) return cell ?? ''
  if (typeof cell === 'number') return cell.toLocaleString('en-US')
  if (row[0] === 'Promedio') return cell ?? ''
  return cell === '' || cell == null ? '0' : cell
}

function formatPercent(cell, ci) {
  if (ci < labelCols.value) return cell ?? ''
  if (cell === '' || cell == null) return ''
  return `${cell}%`
}

function formatCell(cell, row, ci, stat) {
  return mode.value === 'abs' || stat
    ? formatCount(cell, row, ci) // Los estadísticos se formatean siempre como conteo
    : formatPercent(cell, ci)
}
</script>

<template>
  <div>
    <div class="flex items-center justify-between mb-3 px-2 gap-4">
      <h3 class="text-sm font-bold text-[#1e293b]">Resultados</h3>
      <div class="flex gap-1 bg-[#f1f5f9] p-1 rounded-2xl shrink-0">
        <button
          @click="mode = 'abs'"
          class="px-3 py-1 rounded-xl text-xs font-bold transition-colors"
          :class="
            mode === 'abs'
              ? 'bg-white text-[#0d9488] shadow-sm'
              : 'text-[#94a3b8] hover:text-[#64748b]'
          "
        >
          Absolutos
        </button>
        <button
          @click="mode = 'pct'"
          class="px-3 py-1 rounded-xl text-xs font-bold transition-colors"
          :class="
            mode === 'pct'
              ? 'bg-white text-[#0d9488] shadow-sm'
              : 'text-[#94a3b8] hover:text-[#64748b]'
          "
        >
          Relativos
        </button>
      </div>
    </div>

    <div class="overflow-x-auto border border-[#e2e8f0] rounded-lg">
      <table class="w-full">
        <thead>
          <tr class="bg-[rgba(248,250,252,0.5)]">
            <th
              v-for="ci in visibleCols"
              :key="columns[ci]"
              class="px-3 py-2 md:px-6 md:py-4 text-left text-xs font-semibold text-[#64748b] uppercase tracking-wide whitespace-nowrap"
            >
              {{ columns[ci] }}
            </th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="({ cells, stat }, ri) in displayRows"
            :key="ri"
            :class="
              isTotalRow(cells) || stat
                ? 'bg-[rgba(248,250,252,0.3)] border-t-2 border-[#e2e8f0]'
                : 'border-t border-[#f1f5f9] hover:bg-[#f8fafc] transition-colors'
            "
          >
            <td
              v-for="ci in visibleCols"
              :key="ci"
              class="px-3 py-2 md:px-6 md:py-4 text-sm whitespace-nowrap"
              :class="
                isTotalRow(cells)
                  ? 'font-bold text-[#0f172a]'
                  : isNumeric(cellAt(cells, ci), ci)
                    ? 'font-mono text-[#475569]'
                    : 'text-[#1e293b] font-medium'
              "
            >
              <span class="inline-flex items-center gap-1.5">
                <span>{{
                  formatCell(cellAt(cells, ci), cells, ci, stat)
                }}</span>
                <InfoTooltip
                  v-if="diffEntry(ri, cells, ci)"
                  :text="rawTooltip(diffEntry(ri, cells, ci))"
                />
              </span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
