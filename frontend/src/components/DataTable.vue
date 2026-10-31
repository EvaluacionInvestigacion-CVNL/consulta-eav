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
    <h3 class="text-sm font-bold text-[#1e293b] mb-3 px-2">Resultados</h3>
    <div class="overflow-x-auto border border-[#e2e8f0] rounded-lg">
      <table class="w-full">
        <thead>
          <tr class="bg-[rgba(248,250,252,0.5)]">
            <th
              v-for="ci in visibleCols"
              :key="ci"
              class="px-6 py-4 text-left text-xs font-semibold text-[#64748b] uppercase tracking-wide whitespace-nowrap"
            >
              {{ data.column_labels[ci] }}
            </th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="(row, ri) in data.rows"
            :key="ri"
            class="border-t border-[#f1f5f9] hover:bg-[#f8fafc] transition-colors"
          >
            <td
              v-for="ci in visibleCols"
              :key="ci"
              class="px-6 py-4 text-sm whitespace-nowrap"
              :class="
                typeof row[ci] === 'number'
                  ? 'font-mono text-[#475569]'
                  : 'text-[#1e293b] font-medium'
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
