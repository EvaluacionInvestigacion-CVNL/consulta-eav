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

function onWaveChange(e) {
  setWave(e.target.value)
}
</script>

<template>
  <header
    class="bg-white border-b border-[#e2e8f0] px-4 md:px-8 py-3 md:py-4 flex items-center justify-between gap-3 md:gap-6"
  >
    <div class="flex items-center gap-2 min-w-0">
      <button
        v-if="!state.sidebarOpen"
        @click="toggleSidebar"
        title="Mostrar panel"
        class="shrink-0 p-2 rounded-lg text-[#64748b] hover:text-[#fb7e50] hover:bg-[#f8fafc] transition-colors cursor-pointer"
      >
        <PanelLeft class="size-5" />
      </button>
      <h2
        class="font-['Poppins'] text-base md:text-lg whitespace-nowrap overflow-x-auto min-w-0 uppercase text-[#fb7e50] font-extrabold"
      >
        {{ questionText }}
      </h2>
    </div>

    <div
      v-if="state.waves.length > 1"
      class="flex items-center gap-2 shrink-0"
      title="Levantamiento de la encuesta"
    >
      <Calendar class="size-4 text-[#94a3b8] max-md:hidden" />
      <label
        class="text-xs font-medium text-[#64748b] uppercase tracking-wide max-md:hidden"
      >
        Encuesta
      </label>
      <select
        :value="state.waveId"
        :disabled="state.loading"
        @change="onWaveChange"
        class="font-['Poppins'] text-sm font-semibold text-[#334155] bg-[#f8fafc] border border-[#e2e8f0] rounded-lg px-3 py-1.5 cursor-pointer hover:border-[#fb7e50] focus:outline-none focus:border-[#fb7e50] focus:ring-1 focus:ring-[#fb7e50] disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
      >
        <option v-for="w in state.waves" :key="w.wave_id" :value="w.wave_id">
          {{ w.label || w.year }}
        </option>
      </select>
    </div>
  </header>
</template>
