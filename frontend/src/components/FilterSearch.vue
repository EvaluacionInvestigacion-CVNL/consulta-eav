<script setup>
import { ref, computed, watch } from 'vue'
import { Search, Plus, X } from 'lucide-vue-next'
import { state, searchQuestions, addFilter, removeFilter } from '../store.js'
import { useTapToType } from '../tapToType.js'

const MAX_QUESTIONS = 30

const query = ref('')
const root = ref(null)
const { open, typing, onTouchStart, onClick, onFocus, onBlur } =
  useTapToType(root)
const selected = ref(null)
const checked = ref([])
const min = ref('')
const max = ref('')

const ql = computed(() => query.value.trim().toLowerCase())

const attributeItems = computed(() => [
  {
    kind: 'attribute',
    key: 'city_id',
    label: 'Ciudad',
    type: 'options',
    options: state.cities.map((c) => ({ value: c.city_id, label: c.name })),
  },
  ...state.attributes.map((a) => ({
    kind: 'attribute',
    key: a.attribute,
    label: a.label || a.attribute,
    type: a.numeric ? 'range' : 'options',
    options: a.values,
  })),
])

const matchingAttributes = computed(() =>
  ql.value
    ? attributeItems.value.filter((a) =>
        a.label.toLowerCase().includes(ql.value),
      )
    : attributeItems.value,
)

const matchingQuestions = computed(() =>
  searchQuestions(ql.value, MAX_QUESTIONS),
)

const selectedOptions = computed(() => {
  const item = selected.value
  if (!item || item.type !== 'options') return []
  if (item.kind === 'attribute') return item.options
  const q = state.questions.find((x) => x.q_id === item.key)
  return (q?.options || []).map((o) => ({ value: o.option_id, label: o.label }))
})

// Si la dimensión ya tiene filtro, se abre con sus valores para editarlo.
function choose(item) {
  const current = state.filters.find((f) => f[item.kind] === item.key)?.value
  const isRange =
    current && typeof current === 'object' && !Array.isArray(current)
  selected.value = item
  checked.value = current == null || isRange ? [] : [current].flat().map(Number)
  min.value = isRange ? (current.min ?? '') : ''
  max.value = isRange ? (current.max ?? '') : ''
  query.value = ''
  open.value = false
}

function chooseFirst() {
  const first = matchingAttributes.value[0] || matchingQuestions.value[0]
  if (first) choose(first)
}

const canAdd = computed(() => {
  if (!selected.value) return false
  if (selected.value.type === 'options') return checked.value.length > 0
  const hasMin = min.value !== ''
  const hasMax = max.value !== ''
  if (!hasMin && !hasMax) return false
  return !(hasMin && hasMax && min.value > max.value)
})

// Aplicar reemplaza el filtro de esa dimensión: lo marcado es lo que queda.
function add() {
  if (!canAdd.value) return
  const { kind, key, type } = selected.value
  const index = state.filters.findIndex((f) => f[kind] === key)
  if (index >= 0) removeFilter(index)
  if (type === 'range') {
    const range = {}
    if (min.value !== '') range.min = min.value
    if (max.value !== '') range.max = max.value
    addFilter(kind, key, range)
  } else {
    addFilter(kind, key, [...checked.value])
  }
  selected.value = null
}

// Una selección pendiente deja de valer si cambia la ola (otro catálogo) o si
// pasa a ser la pregunta principal (no se filtra una pregunta por sí misma).
watch(
  () => [state.questionId, state.waveId],
  ([id], [, prevWave]) => {
    const item = selected.value
    if (!item) return
    if (
      state.waveId !== prevWave ||
      (item.kind === 'question' && item.key === id)
    )
      selected.value = null
  },
)
</script>

<template>
  <div class="space-y-2">
    <div ref="root" class="relative">
      <div
        class="flex items-center gap-2 bg-[#f1f5f9] border border-gray-300 rounded-4xl px-3 py-2.5"
      >
        <Search class="size-4 text-[#94a3b8] shrink-0" />
        <input
          v-model="query"
          type="search"
          autocomplete="off"
          autocorrect="off"
          autocapitalize="off"
          spellcheck="false"
          enterkeyhint="search"
          @touchstart="onTouchStart"
          @click="onClick"
          @focus="onFocus"
          @blur="onBlur"
          @input="open = true"
          @keydown.esc="open = false"
          @keydown.enter.prevent="chooseFirst"
          placeholder="Filtrar por…"
          class="w-full bg-transparent text-sm text-[#334155] font-medium outline-none"
        />
      </div>

      <div
        v-if="open"
        class="mt-1 w-full bg-white border border-gray-200 rounded-xl py-1 md:absolute md:z-20 md:max-h-72 md:overflow-y-auto md:shadow-lg"
      >
        <p
          class="px-3 pt-2 pb-1 text-[10px] font-semibold text-[#94a3b8] uppercase tracking-wide"
        >
          {{ ql ? 'Atributos' : 'Frecuentes' }}
        </p>
        <button
          v-for="item in matchingAttributes"
          :key="`a-${item.key}`"
          @mousedown.prevent="choose(item)"
          class="w-full text-left px-3 py-1.5 text-sm text-[#334155] hover:bg-[#f0fdfa] flex items-center justify-between"
        >
          <span>{{ item.label }}</span>
          <span v-if="item.type === 'range'" class="text-xs text-[#94a3b8]"
            >rango</span
          >
        </button>
        <p
          v-if="ql && !matchingAttributes.length"
          class="px-3 py-1.5 text-xs text-[#94a3b8]"
        >
          Ningún atributo coincide.
        </p>

        <template v-if="ql">
          <p
            class="px-3 pt-3 pb-1 text-[10px] font-semibold text-[#94a3b8] uppercase tracking-wide"
          >
            Preguntas
          </p>
          <button
            v-for="item in matchingQuestions"
            :key="`q-${item.key}`"
            @mousedown.prevent="choose(item)"
            class="w-full text-left px-3 py-1.5 text-sm text-[#334155] hover:bg-[#f0fdfa]"
          >
            <span class="font-mono text-xs text-[#0d9488] mr-1.5">{{
              item.key
            }}</span>
            <span>{{ item.label }}</span>
          </button>
          <p
            v-if="!matchingQuestions.length"
            class="px-3 py-1.5 text-xs text-[#94a3b8]"
          >
            Ninguna pregunta coincide.
          </p>
        </template>
        <p v-else class="px-3 pt-2 pb-1.5 text-xs text-[#94a3b8]">
          {{
            typing()
              ? 'Escribe para buscar en todas las preguntas.'
              : 'Toca el buscador otra vez para escribir.'
          }}
        </p>
      </div>
    </div>

    <div v-if="selected" class="space-y-2">
      <div class="flex items-center justify-between gap-2">
        <span class="text-xs font-medium text-[#334155] truncate">
          <span
            v-if="selected.kind === 'question'"
            class="font-mono text-[#0d9488] mr-1"
            >{{ selected.key }}</span
          >{{ selected.label }}
        </span>
        <button
          @click="selected = null"
          class="text-[#94a3b8] hover:text-[#0d9488] shrink-0"
          aria-label="Cancelar filtro"
        >
          <X class="size-3.5" />
        </button>
      </div>
      <template v-if="selected.type === 'options'">
        <div
          class="max-h-48 overflow-y-auto bg-[#f1f5f9] border border-gray-300 rounded-xl px-3 py-2 space-y-1.5"
        >
          <label
            v-for="o in selectedOptions"
            :key="o.value"
            class="flex items-start gap-2 text-sm text-[#334155] cursor-pointer"
          >
            <input
              v-model="checked"
              type="checkbox"
              :value="o.value"
              class="mt-0.5 accent-[#0d9488] shrink-0"
            />
            <span>{{ o.label }}</span>
          </label>
        </div>
        <button
          @click="add"
          :disabled="!canAdd"
          class="w-full bg-[#0d9488] hover:bg-[#00685f] disabled:opacity-40 disabled:cursor-not-allowed text-white rounded-4xl py-2 text-sm font-bold flex items-center justify-center gap-1.5 transition-colors"
        >
          <Plus class="size-4" />
          Aplicar{{ checked.length ? ` (${checked.length})` : '' }}
        </button>
      </template>
      <div v-else class="flex gap-2">
        <input
          v-model.number="min"
          type="number"
          placeholder="Mín"
          class="flex-1 min-w-0 bg-[#f1f5f9] border border-gray-300 rounded-4xl px-3 py-2.5 text-sm text-[#334155]"
        />
        <input
          v-model.number="max"
          type="number"
          placeholder="Máx"
          class="flex-1 min-w-0 bg-[#f1f5f9] border border-gray-300 rounded-4xl px-3 py-2.5 text-sm text-[#334155]"
        />
        <button
          @click="add"
          :disabled="!canAdd"
          class="shrink-0 bg-[#0d9488] hover:bg-[#00685f] disabled:opacity-40 disabled:cursor-not-allowed text-white rounded-4xl px-3 flex items-center justify-center transition-colors"
          aria-label="Aplicar filtro"
        >
          <Plus class="size-4" />
        </button>
      </div>
    </div>
  </div>
</template>
