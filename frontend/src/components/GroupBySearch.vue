<script setup>
import { ref, computed } from 'vue'
import { Search, X } from 'lucide-vue-next'
import {
  state,
  searchQuestions,
  setGroupBy,
  clearGroupBy,
  groupByLabel,
  isQuestionGroupBy,
  canCompareYears,
  NO_YEARS_HINT,
} from '../store.js'
import { useTapToType } from '../tapToType.js'

const MAX_QUESTIONS = 30

const query = ref('')
const root = ref(null)
const { open, typing, onTouchStart, onClick, onFocus, onBlur } =
  useTapToType(root)

const ql = computed(() => query.value.trim().toLowerCase())

const frequentItems = computed(() => [
  {
    key: 'year',
    label: 'Año',
    hint: 'comparar entre olas',
    disabled: !canCompareYears.value,
  },
  { key: 'city_id', label: 'Ciudad' },
  ...state.attributes.map((a) => ({
    key: a.attribute,
    label: a.label || a.attribute,
    hint: a.numeric ? 'rangos' : '',
  })),
  ...state.recodes.map((r) => ({ key: r.key, label: r.label })),
])

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

function choose(item) {
  if (item.disabled) return
  setGroupBy(item.key)
  query.value = ''
  open.value = false
}

function chooseFirst() {
  const first =
    matchingFrequent.value.find((i) => !i.disabled) ||
    matchingQuestions.value[0]
  if (first) choose(first)
}
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
          placeholder="Desglosar por… (sexo, edad, ciudad, año)"
          class="w-full bg-transparent text-sm text-[#334155] font-medium outline-none"
        />
      </div>

      <div
        v-if="open"
        class="mt-1 w-full bg-white border border-gray-200 rounded-xl py-1 md:absolute md:z-20 md:max-h-72 md:overflow-y-auto md:shadow-lg"
      >
        <p
          v-if="matchingFrequent.length"
          class="px-3 pt-2 pb-1 text-[10px] font-semibold text-[#94a3b8] uppercase tracking-wide"
        >
          Frecuentes
        </p>
        <button
          v-for="item in matchingFrequent"
          :key="`f-${item.key}`"
          @mousedown.prevent="choose(item)"
          :disabled="item.disabled"
          :title="item.disabled ? NO_YEARS_HINT : undefined"
          class="w-full text-left px-3 py-1.5 text-sm text-[#334155] hover:bg-[#f0fdfa] flex items-center justify-between disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:bg-transparent"
        >
          <span>{{ item.label }}</span>
          <span v-if="item.hint" class="text-xs text-[#94a3b8]">{{
            item.hint
          }}</span>
        </button>
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
            <span
              v-if="item.type === 'range'"
              class="ml-1.5 text-xs text-[#94a3b8]"
              >rangos</span
            >
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
              ? 'Escribe para cruzar con cualquier pregunta.'
              : 'Toca el buscador otra vez para escribir.'
          }}
        </p>
      </div>
    </div>

    <!-- Desglose actual -->
    <div
      v-if="state.groupBy !== 'answer'"
      class="flex items-center gap-2 bg-[#faf5ff] border border-[#e9d8fb] rounded-2xl px-3 py-2"
    >
      <span
        v-if="isQuestionGroupBy"
        class="shrink-0 font-mono text-[11px] font-medium px-1.5 py-0.5 rounded bg-[#e9d8fb] text-[#7e34c3]"
        >{{ state.groupBy }}</span
      >
      <span
        class="flex-1 min-w-0 text-[12px] font-semibold text-[#334155] overflow-hidden text-ellipsis whitespace-nowrap"
        >{{ groupByLabel }}</span
      >
      <button
        @click="clearGroupBy"
        class="shrink-0 text-[#94a3b8] hover:text-[#b91c1c] transition-colors"
        aria-label="Quitar desglose"
      >
        <X class="size-3.5" />
      </button>
    </div>
  </div>
</template>
