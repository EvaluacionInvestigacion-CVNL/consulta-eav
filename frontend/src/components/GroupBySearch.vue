<script setup>
import { ref, computed, nextTick, onMounted, onBeforeUnmount } from 'vue'
import { ChevronDown, Search, X } from 'lucide-vue-next'
import {
  state,
  searchQuestions,
  setGroupBy,
  clearGroupBy,
  groupByLabel,
  isQuestionGroupBy,
  canCompareYears,
  NO_YEARS_HINT,
  isMobile,
} from '../store.js'

const MAX_QUESTIONS = 30

const query = ref('')
const root = ref(null)
const input = ref(null)
const trigger = ref(null)
const open = ref(false)

const ql = computed(() => query.value.trim().toLowerCase())

const frequentItems = computed(() => [
  { key: 'answer', label: 'Respuesta', hint: 'sin desglose' },
  {
    key: 'year',
    label: 'Año',
    hint: 'comparar entre olas',
    disabled: !canCompareYears.value,
  },
  { key: 'city_id', label: 'Ciudad' },
  ...state.attributes.map((a) => ({
    key: a.attribute,
    code: a.question_id,
    label: a.label || a.attribute,
    hint: a.numeric ? 'rangos' : '',
  })),
])

// Código de pregunta del desglose elegido: el de la pregunta misma, o el de la
// pregunta de la que sale el atributo.
const groupByCode = computed(() => {
  if (isQuestionGroupBy.value) return state.groupBy
  return (
    state.attributes.find((a) => a.attribute === state.groupBy)?.question_id ||
    ''
  )
})

const matchingFrequent = computed(() =>
  ql.value
    ? frequentItems.value.filter((i) =>
        i.label.toLowerCase().includes(ql.value),
      )
    : frequentItems.value,
)

const matchingQuestions = computed(() =>
  searchQuestions(ql.value, MAX_QUESTIONS),
)

// La tarjeta muestra el desglose actual y abre la lista. En la compu el cursor
// va directo al campo; en el teléfono no, para que no salga el teclado: casi
// siempre se elige de "Frecuentes".
async function toggle() {
  open.value = !open.value
  if (!open.value) return
  query.value = ''
  if (!isMobile()) {
    await nextTick()
    input.value?.focus()
  }
}

function close() {
  open.value = false
  query.value = ''
}

function closeAndReturn() {
  close()
  trigger.value?.focus()
}

function choose(item) {
  if (item.disabled) return
  setGroupBy(item.key)
  close()
}

function closeOnOutside(e) {
  if (open.value && root.value && !root.value.contains(e.target)) close()
}
onMounted(() => document.addEventListener('pointerdown', closeOnOutside))
onBeforeUnmount(() =>
  document.removeEventListener('pointerdown', closeOnOutside),
)

function chooseFirst() {
  const first =
    matchingFrequent.value.find((i) => !i.disabled) ||
    matchingQuestions.value[0]
  if (first) choose(first)
}
</script>

<template>
  <div ref="root" class="relative">
    <!-- El desglose elegido es el botón que lo cambia, igual que la pregunta -->
    <div
      class="flex items-center gap-2.5 bg-surface border rounded-2xl px-3 transition-colors"
      :class="open ? 'border-brand' : 'border-gray-300 hover:border-brand'"
    >
      <button
        ref="trigger"
        type="button"
        @click="toggle"
        @keydown.esc="close"
        :aria-expanded="open"
        aria-label="Cambiar desglose"
        class="flex-1 min-w-0 py-2.5 flex items-center gap-2.5 text-left cursor-pointer outline-none"
      >
        <span
          v-if="groupByCode"
          class="shrink-0 font-mono text-[11px] font-medium px-1.5 py-0.5 rounded bg-brand-soft text-brand"
          >{{ groupByCode }}</span
        >
        <span
          class="flex-1 min-w-0 text-[13px] font-semibold text-ink-soft overflow-hidden text-ellipsis whitespace-nowrap"
          >{{ groupByLabel }}</span
        >
        <span
          v-if="state.groupBy === 'answer'"
          class="shrink-0 text-[11px] text-faint"
          >sin desglose</span
        >
        <ChevronDown
          class="size-4 text-faint shrink-0 transition-transform"
          :class="open ? 'rotate-180' : ''"
        />
      </button>
      <button
        v-if="state.groupBy !== 'answer'"
        type="button"
        @click="clearGroupBy"
        class="shrink-0 text-faint hover:text-danger transition-colors"
        aria-label="Quitar desglose"
      >
        <X class="size-3.5" />
      </button>
    </div>

    <div
      v-if="open"
      class="mt-1 w-full bg-white border border-gray-200 rounded-xl pb-1 md:absolute md:z-20 md:max-h-80 md:overflow-y-auto md:shadow-lg"
    >
      <div
        class="sticky top-0 bg-white flex items-center gap-2 px-3 py-2 border-b border-gray-100"
      >
        <Search class="size-4 text-faint shrink-0" />
        <input
          ref="input"
          v-model="query"
          type="search"
          autocomplete="off"
          autocorrect="off"
          autocapitalize="off"
          spellcheck="false"
          enterkeyhint="search"
          @keydown.esc="closeAndReturn"
          @keydown.enter.prevent="chooseFirst"
          placeholder="Buscar atributo o pregunta…"
          class="w-full bg-transparent text-sm text-ink-soft font-medium outline-none"
        />
      </div>
      <p
        v-if="matchingFrequent.length"
        class="px-3 pt-2 pb-1 text-[10px] font-semibold text-faint uppercase tracking-wide"
      >
        Frecuentes
      </p>
      <button
        v-for="item in matchingFrequent"
        :key="`f-${item.key}`"
        type="button"
        @click="choose(item)"
        :disabled="item.disabled"
        :title="item.disabled ? NO_YEARS_HINT : undefined"
        class="w-full text-left px-3 py-1.5 text-sm hover:bg-brand-soft flex items-center justify-between disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:bg-transparent"
        :class="
          item.key === state.groupBy
            ? 'text-brand font-semibold'
            : 'text-ink-soft'
        "
      >
        <span>
          <span
            v-if="item.code"
            class="font-mono text-xs font-normal text-brand mr-1.5"
            >{{ item.code }}</span
          >{{ item.label }}</span
        >
        <span v-if="item.hint" class="text-xs font-normal text-faint">{{
          item.hint
        }}</span>
      </button>
      <template v-if="ql">
        <p
          class="px-3 pt-3 pb-1 text-[10px] font-semibold text-faint uppercase tracking-wide"
        >
          Preguntas
        </p>
        <button
          v-for="item in matchingQuestions"
          :key="`q-${item.key}`"
          type="button"
          @click="choose(item)"
          class="w-full text-left px-3 py-1.5 text-sm text-ink-soft hover:bg-brand-soft"
        >
          <span class="font-mono text-xs text-brand mr-1.5">{{
            item.key
          }}</span>
          <span>{{ item.label }}</span>
          <span v-if="item.type === 'range'" class="ml-1.5 text-xs text-faint"
            >rangos</span
          >
        </button>
        <p
          v-if="!matchingQuestions.length"
          class="px-3 py-1.5 text-xs text-faint"
        >
          Ninguna pregunta coincide.
        </p>
      </template>
      <p v-else class="px-3 pt-2 pb-1.5 text-xs text-faint">
        Escribe arriba para cruzar con cualquier pregunta.
      </p>
    </div>
  </div>
</template>
