<script setup>
import { ref, computed } from 'vue'
import { attributeLabel, filterValueLabel } from '../store.js'
import ResultView from './ResultView.vue'

// Los resultados de una respuesta del chat: uno por consulta que hizo el
// modelo. Con más de uno, una pestaña por consulta.
const props = defineProps({
  results: { type: Array, required: true },
})

const active = ref(0)
const current = computed(
  () => props.results[Math.min(active.value, props.results.length - 1)],
)

function breakdownLabel(g) {
  if (!g || g === 'answer') return ''
  if (g === 'year') return 'por año'
  if (g === 'city_id') return 'por municipio'
  if (/^p\d/.test(g)) return `cruzada con ${g}`
  return `por ${attributeLabel(g).toLowerCase()}`
}

function tabLabel(query) {
  if (!query) return 'Resultado'
  const parts = [query.question_id]
  const year = query['año']
  if (year && query.group_by !== 'year') parts.push(year)
  const g = breakdownLabel(query.group_by)
  if (g) parts.push(g)
  for (const f of query.filters || []) parts.push(filterValueLabel(f))
  return parts.join(' · ')
}
</script>

<template>
  <div
    class="bg-white rounded-lg border border-[#e2e8f0] shadow-sm overflow-hidden"
  >
    <div
      v-if="results.length > 1"
      class="flex gap-1 overflow-x-auto px-3 pt-3 border-b border-[#f1f5f9]"
      role="tablist"
    >
      <button
        v-for="(r, i) in results"
        :key="i"
        role="tab"
        :aria-selected="i === active"
        @click="active = i"
        class="shrink-0 whitespace-nowrap px-3 py-1.5 rounded-t-md text-xs font-mono border-b-2 transition-colors"
        :class="
          i === active
            ? 'border-[#7e34c3] text-[#7e34c3] bg-[#7e34c3]/5'
            : 'border-transparent text-[#64748b] hover:text-[#334155]'
        "
      >
        {{ tabLabel(r.query) }}
      </button>
    </div>
    <p
      v-if="results.length > 1 && current.result.question?.q_text"
      class="px-5 pt-3 text-sm text-[#334155]"
    >
      <span class="font-mono text-xs text-[#7e34c3] mr-1">{{
        current.result.question.q_id
      }}</span>
      {{ current.result.question.q_text }}
    </p>
    <ResultView :key="active" :data="current.result" />
  </div>
</template>
