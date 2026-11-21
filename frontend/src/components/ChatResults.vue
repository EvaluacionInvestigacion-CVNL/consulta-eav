<script setup>
import { ref, computed } from 'vue'
import { breakdownLabel, filterValueLabel } from '../store.js'
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
    class="bg-white rounded-2xl border border-line shadow-sm overflow-hidden"
  >
    <div
      v-if="results.length > 1"
      class="flex gap-1 overflow-x-auto px-3 pt-3 border-b border-surface"
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
            ? 'border-brand text-brand bg-brand/5'
            : 'border-transparent text-muted hover:text-ink-soft'
        "
      >
        {{ tabLabel(r.query) }}
      </button>
    </div>
    <!-- Con una sola consulta no hay pestañas, pero se dice igual qué se
         consultó: esta tarjeta es el único lugar donde aparece. -->
    <div v-else class="px-3 pt-3 border-b border-surface">
      <span
        class="inline-block px-3 py-1.5 text-xs font-mono text-brand border-b-2 border-brand"
      >
        {{ tabLabel(results[0].query) }}
      </span>
    </div>
    <p
      v-if="current.result.question?.q_text"
      class="px-5 pt-3 text-sm text-ink-soft"
    >
      <span class="font-mono text-xs text-brand mr-1">{{
        current.result.question.q_id
      }}</span>
      {{ current.result.question.q_text }}
    </p>
    <ResultView :key="active" :data="current.result" />
  </div>
</template>
