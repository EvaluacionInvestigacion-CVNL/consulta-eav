<script setup>
import { ref, reactive, computed, watch, nextTick } from 'vue'
import { Search, X, ChevronRight, Check } from 'lucide-vue-next'
import {
  state,
  questionPicker,
  setGroupByQuestion,
  clearGroupByQuestion,
} from '../store.js'
import InfoTooltip from './InfoTooltip.vue'

const props = defineProps({
  open: { type: Boolean, default: false },
  target: { type: String, default: 'question' },
})
const emit = defineEmits(['close'])

const query = ref('')
const sectionFilter = ref('all')
const expandedGroups = reactive({})
const searchInput = ref(null)

const ql = computed(() => query.value.trim().toLowerCase())
const searching = computed(() => ql.value.length > 0)

// Section chips: "Todas" + one per section, each with its question count.
const chips = computed(() => {
  const model = questionPicker.value
  return [{ key: 'all', label: 'Todas', count: model.total }].concat(
    model.sections.map((s) => ({ key: s.key, label: s.label, count: s.count })),
  )
})

// In 'groupBy' mode the main question can't cross with itself. Any other
// question is eligible: numeric ones cross by ranges.
const isRestricted = computed(() => props.target === 'groupBy')
function eligible(meta) {
  if (!isRestricted.value) return true
  return meta.id !== state.questionId
}
function leafCount(sec) {
  let n = 0
  for (const e of sec.entries) {
    if (e.type === 'q') n += eligible(e) ? 1 : 0
    else n += e.facets.filter(eligible).length
  }
  return n
}

// Flatten the section/group/question tree into a single render list, applying
// the current search and section filter. Mirrors the design's buildPickerItems.
const built = computed(() => {
  const model = questionPicker.value
  const items = []
  const selId = state.questionId
  const q = ql.value

  const pushQ = (meta, indent) => {
    const main = meta.main
    let pre = main
    let mid = ''
    let post = ''
    if (searching.value) {
      const i = main.toLowerCase().indexOf(q)
      if (i >= 0) {
        pre = main.slice(0, i)
        mid = main.slice(i, i + q.length)
        post = main.slice(i + q.length)
      }
    }
    items.push({
      kind: 'question',
      id: meta.id,
      code: meta.id,
      indent,
      showStem: searching.value && !!meta.stem,
      stem: meta.stem,
      info: meta.info,
      pre,
      mid,
      post,
      selected: meta.id === selId,
    })
  }

  const secs = model.sections.filter(
    (s) => sectionFilter.value === 'all' || s.key === sectionFilter.value,
  )

  if (searching.value) {
    for (const sec of secs) {
      const metas = []
      for (const e of sec.entries) {
        if (e.type === 'q') metas.push(e)
        else for (const f of e.facets) metas.push(f)
      }
      const matches = metas.filter((m) => m.search.includes(q) && eligible(m))
      if (!matches.length) continue
      items.push({ kind: 'section', label: sec.label, count: matches.length })
      for (const m of matches) pushQ(m, false)
    }
  } else {
    for (const sec of secs) {
      const lc = isRestricted.value ? leafCount(sec) : sec.count
      if (isRestricted.value && lc === 0) continue // no eligible questions here
      items.push({ kind: 'section', label: sec.label, count: lc })
      for (const e of sec.entries) {
        if (e.type === 'q') {
          if (eligible(e)) pushQ(e, false)
        } else {
          const facets = e.facets.filter(eligible)
          if (!facets.length) continue
          const expanded = !!expandedGroups[e.groupId]
          items.push({
            kind: 'group',
            groupId: e.groupId,
            label: e.label,
            countLabel: `${facets.length} ítems`,
            expanded,
          })
          if (expanded) for (const f of facets) pushQ(f, true)
        }
      }
    }
  }

  return { items, empty: items.length === 0 }
})

function toggleGroup(id) {
  expandedGroups[id] = !expandedGroups[id]
}

function selectQuestion(id) {
  if (props.target === 'groupBy') {
    setGroupByQuestion(id)
  } else {
    state.questionId = id
    // Si la pregunta principal pasa a ser la de desglose, deshaz el cruce para
    // no dejar A == B (el backend lo rechazaría).
    if (state.groupBy === id) clearGroupByQuestion()
  }
  query.value = ''
  emit('close')
}

function clearQuery() {
  query.value = ''
  searchInput.value?.focus()
}

function onKey(e) {
  if (e.key === 'Escape') emit('close')
}

// On open: reset transient state, auto-expand the selected question's group,
// and focus the search box.
watch(
  () => props.open,
  (isOpen) => {
    if (!isOpen) return
    query.value = ''
    sectionFilter.value = 'all'
    const g = questionPicker.value.groupOf.get(state.questionId)
    if (g) expandedGroups[g] = true
    nextTick(() => searchInput.value?.focus())
  },
)
</script>

<template>
  <Teleport to="body">
    <div
      v-if="open"
      @click="emit('close')"
      class="fixed inset-0 z-50 flex items-start justify-center px-4 py-14 bg-[#0f172a]/50"
    >
      <div
        @click.stop
        class="w-215 max-w-[94vw] max-h-[82vh] bg-white rounded-2xl shadow-2xl flex flex-col overflow-hidden"
      >
        <!-- Search header -->
        <div class="p-4 pb-3 border-b border-[#f1f5f9]">
          <p
            v-if="target === 'groupBy'"
            class="text-[12px] font-semibold text-[#5e2494] mb-2.5"
          >
            Cruzar por otra pregunta — elige la variable de desglose (las
            numéricas se agrupan por rangos).
          </p>
          <div
            class="flex items-center gap-2.5 bg-[#f1f5f9] rounded-xl px-3.5 py-2.5"
          >
            <Search class="size-4.5 text-[#94a3b8] shrink-0" />
            <input
              ref="searchInput"
              v-model="query"
              @keydown="onKey"
              placeholder="Busca por tema, palabra o código — p. ej. discriminación, mujer, p80"
              class="flex-1 bg-transparent border-none outline-none text-[15px] text-[#1e293b] placeholder:text-[#94a3b8]"
            />
            <button
              v-if="query.length"
              @click="clearQuery"
              class="text-[#94a3b8] hover:text-[#64748b] flex"
              aria-label="Limpiar búsqueda"
            >
              <X class="size-4" />
            </button>
          </div>
          <div class="flex gap-1.5 mt-3 overflow-x-auto pb-0.5">
            <button
              v-for="chip in chips"
              :key="chip.key"
              @click="sectionFilter = chip.key"
              class="shrink-0 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-semibold transition-colors"
              :class="
                sectionFilter === chip.key
                  ? 'bg-[#0d9488] text-white'
                  : 'bg-[#f1f5f9] text-[#64748b] hover:bg-[#e2e8f0]'
              "
            >
              <span>{{ chip.label }}</span>
              <span class="text-[10px] opacity-70">{{ chip.count }}</span>
            </button>
          </div>
        </div>

        <!-- List -->
        <div class="flex-1 overflow-y-auto p-2">
          <template v-for="(it, idx) in built.items" :key="idx">
            <!-- Section header -->
            <div
              v-if="it.kind === 'section'"
              class="px-2.5 pt-3.5 pb-1.5 flex items-center gap-2"
            >
              <span
                class="text-[11px] font-bold text-[#94a3b8] uppercase tracking-wider"
                >{{ it.label }}</span
              >
              <span class="text-[11px] text-[#cbd5e1]">{{ it.count }}</span>
            </div>

            <!-- Battery group toggle -->
            <button
              v-else-if="it.kind === 'group'"
              @click="toggleGroup(it.groupId)"
              class="w-full text-left flex items-start gap-2.5 px-3 py-2.5 my-0.5 rounded-lg bg-[#faf5ff] border-l-[3px] border-[#7e34c3] cursor-pointer"
            >
              <ChevronRight
                class="size-3.5 mt-0.5 text-[#7e34c3] shrink-0 transition-transform"
                :class="it.expanded ? 'rotate-90' : ''"
                stroke-width="2.5"
              />
              <span class="flex-1 min-w-0">
                <span
                  class="block text-[13px] font-bold text-[#5e2494] wrap-break-word"
                  >{{ it.label }}</span
                >
              </span>
              <span
                class="text-[11px] font-bold text-[#7e34c3] bg-[#f3e8ff] px-2.5 py-0.5 rounded-full whitespace-nowrap shrink-0"
                >{{ it.countLabel }}</span
              >
            </button>

            <!-- Question row -->
            <div
              v-else
              @click="selectQuestion(it.id)"
              class="flex items-center gap-2.5 px-2.5 py-2 my-px rounded-lg cursor-pointer"
              :class="[
                it.indent ? 'pl-7' : '',
                it.selected ? 'bg-[#f0fdfa]' : 'bg-white hover:bg-[#f8fafc]',
              ]"
            >
              <span
                class="shrink-0 font-mono text-[11px] font-medium px-1.5 py-0.5 rounded"
                :class="
                  it.selected
                    ? 'bg-[#0d9488] text-white'
                    : 'bg-[#eef2f6] text-[#64748b]'
                "
                >{{ it.code }}</span
              >
              <span class="flex-1 min-w-0">
                <span
                  v-if="it.showStem"
                  class="block text-[11px] text-[#94a3b8] wrap-break-word"
                  >{{ it.stem }}</span
                >
                <span
                  class="block text-sm text-[#1e293b]"
                  :class="it.selected ? 'font-semibold' : 'font-medium'"
                  >{{ it.pre
                  }}<mark
                    v-if="it.mid"
                    class="bg-[#fde68a] text-inherit rounded-xs p-0"
                    >{{ it.mid }}</mark
                  >{{ it.post }}</span
                >
              </span>
              <InfoTooltip v-if="it.info" :text="it.info" />
              <Check
                v-if="it.selected"
                class="size-4 text-[#0d9488] shrink-0"
                stroke-width="2.5"
              />
            </div>
          </template>

          <div v-if="built.empty" class="px-4 py-12 text-center text-[#94a3b8]">
            <p class="m-0 text-sm">
              No se encontraron preguntas para “{{ query }}”.
            </p>
          </div>
        </div>

        <!-- Footer -->
        <div
          class="px-4 py-2.5 border-t border-[#f1f5f9] flex items-center justify-end text-[11px] text-[#94a3b8]"
        >
          <span>{{ questionPicker.total }} preguntas</span>
        </div>
      </div>
    </div>
  </Teleport>
</template>
