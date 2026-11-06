<script setup>
import { ref, computed, watch } from 'vue'
import {
  Eye,
  Copy,
  Check,
  Play,
  X,
  SlidersHorizontal,
  Sparkles,
  Plus,
  MessageSquare,
  Trash2,
  Search,
  PanelLeft,
} from 'lucide-vue-next'
import {
  state,
  sqlPreview,
  canRun,
  runCurrentQuery,
  clearFilters,
  removeFilter,
  filterValueLabel,
  attributeLabel,
  querySummary,
  questionPicker,
  setQueryMode,
  newConversation,
  loadConversation,
  deleteConversation,
  canCompareYears,
  toggleSidebar,
  isMobile,
  hasFeature,
} from '../store.js'
import QuestionPicker from './QuestionPicker.vue'
import FilterSearch from './FilterSearch.vue'
import GroupBySearch from './GroupBySearch.vue'
import InfoTooltip from './InfoTooltip.vue'

// Modal para buscar la pregunta principal.
const pickerOpen = ref(false)
const selectedQuestionMeta = computed(
  () => questionPicker.value.byId.get(state.questionId) || null,
)

function relativeTime(ts) {
  const diff = Date.now() - ts
  const min = Math.floor(diff / 60000)
  if (min < 1) return 'ahora'
  if (min < 60) return `hace ${min} min`
  const h = Math.floor(min / 60)
  if (h < 24) return `hace ${h} h`
  const d = Math.floor(h / 24)
  if (d === 1) return 'ayer'
  return `hace ${d} d`
}

const sqlCopied = ref(false)
const showSQL = ref(false)

async function copySQL() {
  try {
    await navigator.clipboard.writeText(sqlPreview.value)
    sqlCopied.value = true
    setTimeout(() => {
      sqlCopied.value = false
    }, 2000)
  } catch (e) {
    console.error('Clipboard write failed:', e)
  }
}

// En el teléfono el panel tapa el resultado: al ejecutar se cierra solo.
function runAndClose() {
  runCurrentQuery()
  if (isMobile()) state.sidebarOpen = false
}

// Si cambias a una pregunta sin equivalencia y tenías "Año" seleccionado, resetea.
watch(canCompareYears, (ok) => {
  if (!ok && state.groupBy === 'year') {
    state.groupBy = 'answer'
  }
})
</script>

<template>
  <Transition
    enter-active-class="transition-[margin] duration-200 ease-out"
    leave-active-class="transition-[margin] duration-200 ease-in"
    enter-from-class="-ml-70"
    leave-to-class="-ml-70"
  >
    <aside
      v-show="state.sidebarOpen"
      class="w-70 shrink-0 bg-white border-r border-[#e2e8f0] flex flex-col max-md:fixed max-md:inset-y-0 max-md:left-0 max-md:z-40 max-md:shadow-2xl"
    >
      <!-- Logo -->
      <div class="py-2 px-4 border-b border-[#e2e8f0]">
        <div class="flex items-center justify-between gap-3 px-2 py-2">
          <div class="flex items-center">
            <img
              src="/minilogo.webp"
              alt="Logo"
              class="size-6 object-contain max-w-none"
            />
            <span
              class="font-extrabold text-[#7e34c3] text-center text-[20px] tracking-tight mx-1"
              >Así Vamos</span
            >
          </div>
          <button
            @click="toggleSidebar"
            title="Ocultar panel"
            class="shrink-0 p-2 rounded-lg text-[#64748b] hover:text-[#fb7e50] hover:bg-[#f8fafc] transition-colors cursor-pointer"
          >
            <PanelLeft class="size-5" />
          </button>
        </div>
      </div>

      <!-- Query Controls -->
      <div class="flex-1 p-4 space-y-6 overflow-y-auto">
        <!-- Modo de Consulta -->
        <div>
          <label
            class="text-xs font-medium text-[#64748b] uppercase tracking-wide mb-2 block"
          >
            Modo de Consulta
          </label>
          <div class="grid grid-cols-2 gap-2 bg-[#f1f5f9] p-1 rounded-2xl">
            <button
              @click="setQueryMode('manual')"
              class="flex items-center justify-center gap-1.5 py-2 rounded-xl text-sm font-bold transition-colors"
              :class="
                state.queryMode === 'manual'
                  ? 'bg-white text-[#0d9488] shadow-sm'
                  : 'text-[#94a3b8] hover:text-[#64748b]'
              "
            >
              <SlidersHorizontal class="size-4" />
              Manual
            </button>
            <button
              @click="setQueryMode('ai')"
              class="flex items-center justify-center gap-1.5 py-2 rounded-xl text-sm font-bold transition-colors"
              :class="
                state.queryMode === 'ai'
                  ? 'bg-white text-[#7e34c3] shadow-sm'
                  : 'text-[#94a3b8] hover:text-[#64748b]'
              "
            >
              <Sparkles class="size-4" />
              IA
            </button>
          </div>
        </div>

        <!-- Manual query builder controls -->
        <template v-if="state.queryMode === 'manual'">
          <!-- Pregunta -->
          <div>
            <div class="flex items-center gap-2 mb-2">
              <span
                class="size-5 shrink-0 rounded-full bg-[#0d9488] text-white text-[11px] font-bold flex items-center justify-center"
                >1</span
              >
              <span
                class="text-xs font-medium text-[#64748b] uppercase tracking-wide"
                >Pregunta</span
              >
            </div>
            <button
              @click="pickerOpen = true"
              class="w-full text-left bg-[#f1f5f9] border border-gray-300 rounded-2xl px-3 py-2.5 cursor-pointer flex items-center gap-2.5 hover:border-[#0d9488] transition-colors"
            >
              <span
                v-if="selectedQuestionMeta"
                class="shrink-0 font-mono text-[11px] font-medium px-1.5 py-0.5 rounded bg-[#e9d8fb] text-[#7e34c3]"
                >{{ selectedQuestionMeta.id }}</span
              >
              <span class="flex-1 min-w-0">
                <span
                  class="block text-[13px] font-semibold text-[#334155] overflow-hidden text-ellipsis whitespace-nowrap"
                  >{{
                    selectedQuestionMeta
                      ? selectedQuestionMeta.main
                      : '— Selecciona una pregunta —'
                  }}</span
                >
                <span
                  class="block text-[11px] text-[#94a3b8] overflow-hidden text-ellipsis whitespace-nowrap mt-px"
                  >{{
                    selectedQuestionMeta
                      ? selectedQuestionMeta.note ||
                        selectedQuestionMeta.sectionLabel
                      : 'Busca entre todas las preguntas'
                  }}</span
                >
              </span>
              <InfoTooltip
                v-if="selectedQuestionMeta && selectedQuestionMeta.info"
                :text="selectedQuestionMeta.info"
              />
              <Search class="size-4 text-[#94a3b8] shrink-0" />
            </button>
          </div>

          <!-- Paso 2: desglose -->
          <div>
            <div class="flex items-center gap-2 mb-2">
              <span
                class="size-5 shrink-0 rounded-full bg-[#0d9488] text-white text-[11px] font-bold flex items-center justify-center"
                >2</span
              >
              <span
                class="text-xs font-medium text-[#64748b] uppercase tracking-wide"
                >Desglosar por
                <span class="normal-case font-normal text-[#94a3b8]"
                  >(opcional)</span
                ></span
              >
            </div>
            <GroupBySearch />
          </div>

          <!-- Agregar filtro: atributos y preguntas en un solo buscador -->
          <div>
            <div class="flex items-center gap-2 mb-2">
              <span
                class="size-5 shrink-0 rounded-full bg-[#0d9488] text-white text-[11px] font-bold flex items-center justify-center"
                >3</span
              >
              <span
                class="text-xs font-medium text-[#64748b] uppercase tracking-wide"
                >Filtrar
                <span class="normal-case font-normal text-[#94a3b8]"
                  >(opcional)</span
                ></span
              >
            </div>
            <FilterSearch />
          </div>

          <!-- Filtros aplicados -->
          <div v-if="state.filters.length">
            <div class="flex items-center justify-between mb-2">
              <label
                class="text-xs font-medium text-[#64748b] uppercase tracking-wide"
              >
                Filtros
              </label>
              <button
                @click="clearFilters"
                class="text-xs text-[#94a3b8] hover:text-[#0d9488] font-medium"
              >
                Limpiar
              </button>
            </div>
            <div class="flex flex-wrap gap-1.5">
              <span
                v-for="(f, i) in state.filters"
                :key="i"
                class="inline-flex items-center gap-1 bg-[#f0fdfa] text-[#0d9488] text-xs font-medium px-2 py-1 rounded"
              >
                <span
                  >{{ f.question ?? attributeLabel(f.attribute) }}:
                  {{ filterValueLabel(f) }}</span
                >
                <button
                  @click="removeFilter(i)"
                  class="hover:text-[#00685f]"
                  aria-label="Quitar filtro"
                >
                  <X class="size-3" />
                </button>
              </span>
            </div>
          </div>

          <!-- Initial only toggle -->
          <div>
            <label class="flex items-center gap-3 cursor-pointer">
              <input
                type="checkbox"
                v-model="state.initialOnly"
                class="size-4 accent-[#0d9488] cursor-pointer"
              />
              <span class="flex-1 text-sm font-medium text-[#1e293b]">
                Proyectar a la población
              </span>
              <InfoTooltip
                text="Restringe a respondientes iniciales y aplica el factor de expansión factor_cvnl. Apaga para ver conteos crudos del muestreo."
              />
            </label>
          </div>

          <!-- SQL Preview Toggle -->
          <div v-if="hasFeature('mostrar_sql')">
            <button
              @click="showSQL = !showSQL"
              class="w-full flex items-center justify-between p-3 bg-[#f8fafc] hover:bg-[#f1f5f9] rounded-lg transition-colors"
            >
              <span
                class="text-xs font-medium text-[#64748b] uppercase tracking-wide"
              >
                SQL Generado
              </span>
              <Eye
                :class="[
                  'size-4',
                  showSQL ? 'text-[#0d9488]' : 'text-[#94a3b8]',
                ]"
              />
            </button>

            <div v-if="showSQL" class="mt-2">
              <div class="flex items-center justify-end mb-2">
                <button
                  @click="copySQL"
                  class="flex items-center gap-1 text-[#0d9488] hover:text-[#00685f] transition-colors"
                >
                  <template v-if="sqlCopied">
                    <Check class="size-3" />
                    <span class="text-xs font-bold">Copiado</span>
                  </template>
                  <template v-else>
                    <Copy class="size-3" />
                    <span class="text-xs font-bold">Copiar</span>
                  </template>
                </button>
              </div>
              <div
                class="bg-[#0f172a] rounded-lg p-4 border border-[#1e293b] shadow-inner"
              >
                <pre
                  class="text-xs font-mono leading-relaxed text-code-fg whitespace-pre-wrap break-all m-0 text-[rgba(45,212,191,0.9)]"
                  >{{ sqlPreview }}</pre
                >
              </div>
            </div>
          </div>
        </template>

        <!-- AI mode: conversation history -->
        <template v-else>
          <button
            @click="newConversation"
            class="w-full flex items-center justify-center gap-2 bg-[#7e34c3] hover:bg-[#5e2494] text-white rounded-2xl px-4 py-2.5 text-sm font-bold shadow-sm transition-colors"
          >
            <Plus class="size-4" />
            Nueva conversación
          </button>

          <div>
            <label
              class="text-xs font-medium text-[#64748b] uppercase tracking-wide mb-2 block"
            >
              Conversaciones recientes
            </label>

            <p
              v-if="!state.conversations.length"
              class="text-xs text-[#94a3b8] leading-snug"
            >
              Tus conversaciones aparecerán aquí. Se guardan las 5 más recientes
              en este navegador.
            </p>

            <div v-else class="space-y-1">
              <div
                v-for="c in state.conversations"
                :key="c.id"
                @click="loadConversation(c.id)"
                class="group flex items-center gap-2 px-3 py-2 rounded-xl cursor-pointer transition-colors"
                :class="
                  c.id === state.currentConversationId
                    ? 'bg-[#7e34c3]/10 text-[#7e34c3]'
                    : 'text-[#475569] hover:bg-[#f1f5f9]'
                "
              >
                <MessageSquare class="size-4 shrink-0" />
                <div class="flex-1 min-w-0">
                  <p class="text-sm font-medium truncate">{{ c.title }}</p>
                  <!-- La respuesta llega a la conversación desde la que se
                     preguntó, aunque el usuario se haya cambiado de chat. -->
                  <p
                    v-if="state.pendingChats.includes(c.id)"
                    class="text-[10px] text-[#7e34c3] animate-pulse"
                  >
                    Respondiendo…
                  </p>
                  <p v-else class="text-[10px] text-[#94a3b8]">
                    {{ relativeTime(c.updatedAt) }}
                  </p>
                </div>
                <button
                  @click.stop="deleteConversation(c.id)"
                  class="opacity-0 group-hover:opacity-100 text-[#94a3b8] hover:text-[#b91c1c] transition-opacity shrink-0"
                  aria-label="Eliminar conversación"
                >
                  <Trash2 class="size-3.5" />
                </button>
              </div>
            </div>
          </div>
        </template>
      </div>

      <!-- Execute Button (manual mode only) -->
      <div
        v-if="state.queryMode === 'manual'"
        class="p-4 border-t border-[#e2e8f0] space-y-3"
      >
        <p
          v-if="querySummary"
          class="text-xs text-[#475569] bg-[#f8fafc] border border-[#e2e8f0] rounded-lg px-3 py-2 leading-relaxed"
        >
          <span class="font-semibold text-[#334155]">Verás:</span>
          {{ querySummary }}
        </p>
        <button
          @click="runAndClose"
          :disabled="!canRun"
          class="w-full bg-[#0d9488] hover:bg-[#00685f] disabled:opacity-45 disabled:cursor-not-allowed text-white rounded px-4 py-3 flex items-center justify-center gap-2 font-bold shadow-lg shadow-[#0d9488]/20 transition-colors"
        >
          <Play class="size-4 fill-white" />
          Ejecutar consulta
        </button>
      </div>

      <QuestionPicker :open="pickerOpen" @close="pickerOpen = false" />
    </aside>
  </Transition>
</template>
