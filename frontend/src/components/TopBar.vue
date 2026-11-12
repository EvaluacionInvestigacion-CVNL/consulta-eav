<script setup>
import { computed } from 'vue'
import { PanelLeft } from 'lucide-vue-next'
import { state, selectedQuestion, toggleSidebar } from '../store.js'

const questionText = computed(() =>
  state.queryMode === 'ai'
    ? 'Haz una pregunta'
    : selectedQuestion.value?.q_text ||
      'Selecciona una pregunta en el panel izquierdo',
)

// Antelínea sobre la pregunta: qué estás viendo y de qué año. El año se elige
// en el panel; aquí se repite para que se vea aunque el panel esté cerrado.
const eyebrow = computed(() => {
  if (state.queryMode === 'ai') return 'Modo IA'
  const q = selectedQuestion.value
  const parts = [q ? `Pregunta ${q.q_id}` : 'Consulta manual']
  if (state.waveId) parts.push(state.waveId)
  return parts.join(' · ')
})
</script>

<template>
  <header
    class="bg-white border-b border-line px-4 md:px-8 py-3 md:py-4 flex items-center justify-between gap-3 md:gap-6"
  >
    <div class="flex items-center gap-2 min-w-0">
      <button
        v-if="!state.sidebarOpen"
        @click="toggleSidebar"
        title="Mostrar panel"
        class="shrink-0 p-2 rounded-lg text-muted hover:text-brand hover:bg-brand-soft transition-colors cursor-pointer"
      >
        <PanelLeft class="size-5" />
      </button>
      <div class="min-w-0">
        <p
          class="text-[11px] font-semibold uppercase tracking-wider text-brand leading-none mb-1"
        >
          {{ eyebrow }}
        </p>
        <h2
          class="text-sm md:text-base font-semibold text-ink leading-snug line-clamp-2"
          :title="questionText"
        >
          {{ questionText }}
        </h2>
      </div>
    </div>
  </header>
</template>
