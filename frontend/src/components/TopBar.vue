<script setup>
import { computed } from 'vue'
import { Calendar, PanelLeft } from 'lucide-vue-next'
import { state, selectedQuestion, setWave, toggleSidebar } from '../store.js'

const questionText = computed(() =>
  state.queryMode === 'ai'
    ? 'Haz una pregunta'
    : selectedQuestion.value?.q_text ||
      'Selecciona una pregunta en el panel izquierdo',
)

// Antelínea sobre la pregunta: qué estás viendo.
const eyebrow = computed(() => {
  if (state.queryMode === 'ai') return 'Modo IA'
  const q = selectedQuestion.value
  return q ? `Pregunta ${q.q_id}` : 'Consulta manual'
})

function onWaveChange(e) {
  setWave(e.target.value)
}
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

    <div
      v-if="state.waves.length > 1"
      class="flex items-center gap-2 shrink-0"
      title="Levantamiento de la encuesta"
    >
      <Calendar class="size-4 text-faint max-md:hidden" />
      <label
        class="text-xs font-medium text-muted uppercase tracking-wide max-md:hidden"
      >
        Encuesta
      </label>
      <select
        :value="state.waveId"
        :disabled="state.loading"
        @change="onWaveChange"
        class="text-sm font-semibold text-ink-soft bg-white border border-line rounded-full px-4 py-1.5 cursor-pointer hover:border-brand focus:outline-none focus:border-brand focus:ring-1 focus:ring-brand disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
      >
        <option v-for="w in state.waves" :key="w.wave_id" :value="w.wave_id">
          {{ w.label || w.year }}
        </option>
      </select>
    </div>
  </header>
</template>
