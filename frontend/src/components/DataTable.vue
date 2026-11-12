<script setup>
import { computed } from 'vue'

const props = defineProps({
  data: { type: Object, required: true },
})

// El código de la opción (id_respuesta) le sirve al equipo, no al lector.
const visibleCols = computed(() =>
  (props.data?.column_labels ?? [])
    .map((_, i) => i)
    .filter((i) => props.data.column_labels[i] !== 'id_respuesta'),
)

const TOTAL_LABEL_RE = /^(Total|Respuestas|Mínimo|Máximo)$/i

function formatCell(cell, ci) {
  if (typeof cell !== 'number') return cell ?? ''
  const label = props.data?.column_labels?.[ci]
  if (label && TOTAL_LABEL_RE.test(label)) {
    return cell.toLocaleString('en-US')
  }
  return cell
}
</script>

<template>
  <div>
    <h3 class="text-sm font-bold text-ink mb-3 px-2">Resultados</h3>
    <div class="overflow-x-auto border border-line rounded-lg">
      <table class="w-full">
        <thead>
          <tr class="bg-surface-soft">
            <th
              v-for="ci in visibleCols"
              :key="ci"
              class="px-3 py-2 md:px-6 md:py-4 text-left text-xs font-semibold text-muted uppercase tracking-wide whitespace-nowrap"
            >
              {{ data.column_labels[ci] }}
            </th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="(row, ri) in data.rows"
            :key="ri"
            class="border-t border-surface hover:bg-surface-soft transition-colors"
          >
            <td
              v-for="ci in visibleCols"
              :key="ci"
              class="px-3 py-2 md:px-6 md:py-4 text-sm whitespace-nowrap"
              :class="
                typeof row[ci] === 'number'
                  ? 'tabular-nums text-ink-soft'
                  : 'text-ink font-medium'
              "
            >
              {{ formatCell(row[ci], ci) }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
