import { reactive, computed } from 'vue'
import * as api from './api.js'

// Tracks state of query, UI and chat history
export const state = reactive({
  features: [],
  waves: [],
  waveId: '',
  questions: [],
  attributes: [],
  recodes: [],
  presets: [],
  cities: [],
  questionId: '',
  groupBy: 'answer',
  filters: [],
  initialOnly: true,
  appliedPreset: '',
  lastResult: null,
  activeTab: 'chart',
  loading: false,
  error: null,
  queryMode: 'manual',
  sidebarOpen: true,
  chatMessages: [],
  pendingChats: [], // Ids de las conversaciones con una petición activa.
  conversations: [],
  currentConversationId: null,
})

const CHAT_STORAGE_KEY = 'eav-chat-conversations'
const MAX_CONVERSATIONS = 5

export const selectedQuestion = computed(
  () => state.questions.find((q) => q.q_id === state.questionId) || null,
)

// La conversación en pantalla está esperando respuesta.
export const chatLoading = computed(() =>
  state.pendingChats.includes(state.currentConversationId),
)

const SECTION_LABELS = {
  generales: 'Generales',
  variables_generales: 'Generales',
  economia_y_trabajo: 'Economía y trabajo',
  educacion: 'Educación',
  salud: 'Salud',
  seguridad: 'Seguridad',
  seguridad_y_justicia: 'Seguridad y justicia',
  movilidad: 'Movilidad',
  desarrollo_urbano: 'Desarrollo urbano',
  desarrollo_social_y_economico: 'Desarrollo social y económico',
  medio_ambiente: 'Medio ambiente',
  gobierno: 'Gobierno',
  migracion_y_discriminacion: 'Migración y discriminación',
  migracion: 'Migración',
  discriminacion: 'Discriminación',
  participacion_ciudadana: 'Participación ciudadana',
  como_vamos_nuevo_leon: 'Cómo Vamos, Nuevo León',
  orgullo_de_nuevo_leon: 'Orgullo de Nuevo León',
  principal_problema_de_nuevo_leon: 'Principal problema de Nuevo León',
  problema_de_desarrollo_social: 'Problema de desarrollo social',
  eje_1_desarrollo_sustentable: 'Eje 1: Desarrollo sustentable',
  datos_generales_de_la_poblacion_encuestada: 'Datos generales',
  derivadas: 'Variables derivadas',
}

export const questionsBySection = computed(() => {
  const groups = new Map()
  for (const section of Object.keys(SECTION_LABELS)) groups.set(section, [])
  for (const q of state.questions) {
    const section = q.q_section || 'otros'
    if (!groups.has(section)) groups.set(section, [])
    groups.get(section).push(q)
  }
  const out = []
  for (const [section, questions] of groups) {
    if (questions.length)
      out.push({
        key: section,
        label: SECTION_LABELS[section] || section,
        questions,
      })
  }
  return out
})

function questionSearch(q, block, info, sectionLabel) {
  return `${q.q_id} ${q.q_text || ''} ${block} ${info} ${sectionLabel}`.toLowerCase()
}

export const questionPicker = computed(() => {
  const sections = []
  const byId = new Map()
  const groupOf = new Map()
  let groupSeq = 0

  for (const grp of questionsBySection.value) {
    const sectionLabel = grp.label

    // How many questions share each block within this section.
    const blockCounts = new Map()
    for (const q of grp.questions) {
      const block = (q.q_block || '').trim()
      if (block) blockCounts.set(block, (blockCounts.get(block) || 0) + 1)
    }

    const entries = []
    const groupByBlock = new Map()
    for (const q of grp.questions) {
      const block = (q.q_block || '').trim()
      const info = (q.q_info || '').trim()
      const meta = {
        id: q.q_id,
        main: q.q_text || q.q_id,
        qType: q.q_type,
        sectionLabel,
        block,
        info,
        note: block || info,
        stem: '',
        groupId: null,
        search: questionSearch(q, block, info, sectionLabel),
      }
      if (block && blockCounts.get(block) > 1) {
        let entry = groupByBlock.get(block)
        if (!entry) {
          entry = {
            type: 'group',
            groupId: `g${groupSeq++}`,
            label: block,
            facets: [],
          }
          groupByBlock.set(block, entry)
          entries.push(entry)
        }
        meta.groupId = entry.groupId
        meta.stem = block
        entry.facets.push(meta)
        groupOf.set(meta.id, entry.groupId)
      } else {
        entries.push({ type: 'q', ...meta })
      }
      byId.set(meta.id, meta)
    }

    sections.push({
      key: grp.key,
      label: sectionLabel,
      count: grp.questions.length,
      entries,
    })
  }

  return { sections, byId, groupOf, total: state.questions.length }
})

// group_by can be a question id (cross-tab). Distinguish it from the reserved
// keys and from attribute/recode names, which are the other legal group_by values.
const RESERVED_GROUP_BY = new Set(['answer', 'year', 'city_id'])

export const isQuestionGroupBy = computed(() => {
  const g = state.groupBy
  if (!g || RESERVED_GROUP_BY.has(g)) return false
  if (state.attributes.some((a) => a.attribute === g)) return false
  if (state.recodes.some((r) => r.key === g)) return false
  return questionPicker.value.byId.has(g) // a real question id
})

export const groupByQuestionMeta = computed(() =>
  isQuestionGroupBy.value
    ? questionPicker.value.byId.get(state.groupBy) || null
    : null,
)

// Set/clear the breakdown question chosen for a cross-tab.
export function setGroupByQuestion(id) {
  state.groupBy = id
  state.appliedPreset = ''
}

export function clearGroupByQuestion() {
  state.groupBy = 'answer'
  state.appliedPreset = ''
}

const attributeValueMap = computed(() => {
  const out = new Map()
  for (const attr of state.attributes) {
    const valueToLabel = new Map()
    for (const v of attr.values) valueToLabel.set(v.value, v.label)
    out.set(attr.attribute, valueToLabel)
  }
  return out
})

const cityNameMap = computed(() => {
  const out = new Map()
  for (const city of state.cities) out.set(city.city_id, city.name)
  return out
})

// Un rango {min, max} de un filtro por pregunta numérica, para mostrarlo.
function rangeLabel({ min, max }) {
  if (min != null && max != null) return `${min}-${max}`
  return min != null ? `${min} o más` : `hasta ${max}`
}

export function filterValueLabel(filter) {
  const v = filter.value
  if (v && typeof v === 'object' && !Array.isArray(v)) return rangeLabel(v)
  if (filter.question) {
    const q = state.questions.find((x) => x.q_id === filter.question)
    const labels = new Map(
      (q?.options || []).map((o) => [o.option_id, o.label]),
    )
    return v.map((x) => labels.get(x) ?? String(x)).join(', ')
  }
  const inner =
    filter.attribute === 'city_id'
      ? cityNameMap.value
      : attributeValueMap.value.get(filter.attribute)
  if (Array.isArray(v)) {
    return v.map((x) => inner?.get(x) ?? String(x)).join(', ')
  }
  return inner?.get(v) ?? String(v)
}

function cleanSQL(sql) {
  return sql
    .split('\n')
    .map((l) => l.trim())
    .filter((l) => l !== '')
    .join('\n')
}

export const sqlPreview = computed(() => {
  if (state.lastResult?.sql) return cleanSQL(state.lastResult.sql)
  if (!state.questionId) return '-- Selecciona una pregunta'
  return '-- Ejecuta la consulta para ver el SQL generado'
})

export const canRun = computed(() => !!state.questionId && !state.loading)

// Trae los catálogos de una ola.
// Sin `waveId` el servidor responde con la ola marcada por `is_default`.
async function fetchCatalog(waveId) {
  const [questions, attributes, cities, presets] = await Promise.all([
    api.fetchQuestions(waveId),
    api.fetchAttributes(waveId),
    api.fetchCities(waveId),
    api.fetchPresets(waveId),
  ])
  return { questions, attributes, cities, presets }
}

function applyCatalog(catalog) {
  state.questions = catalog.questions
  state.attributes = catalog.attributes
  state.cities = catalog.cities
  state.presets = catalog.presets
}

// Load the wave-scoped catalogs (questions/attributes/cities) for state.waveId.
async function loadCatalog() {
  applyCatalog(await fetchCatalog(state.waveId))
}

export async function init() {
  try {
    const [waves, recodes, catalog, features] = await Promise.all([
      api.fetchWaves(),
      api.fetchRecodes(),
      fetchCatalog(),
      api.fetchFeatures(),
    ])
    state.features = features
    state.waves = waves
    state.waveId =
      (waves.find((w) => w.is_default) || waves[0] || {}).wave_id || ''
    state.recodes = recodes
    applyCatalog(catalog)
    loadConversations()
  } catch (e) {
    state.error = 'Error conectando al servidor'
    console.error(e)
  }
}

// Switch the active survey wave: reload catalogs and reset the query, since the
// question set, options and filter values differ between waves.
export async function setWave(waveId) {
  if (!waveId || waveId === state.waveId) return
  state.waveId = waveId
  state.questionId = ''
  state.filters = []
  state.groupBy = 'answer'
  state.appliedPreset = ''
  state.lastResult = null
  state.error = null
  state.loading = true
  try {
    await loadCatalog()
  } catch (e) {
    state.error = 'Error al cambiar de ola'
    console.error(e)
  } finally {
    state.loading = false
  }
}

// Feature flags prendidos.
export function hasFeature(name) {
  return state.features.includes(name)
}

export const currentWave = computed(
  () => state.waves.find((w) => w.wave_id === state.waveId) || null,
)

export function applyPreset(key) {
  const p = state.presets.find((x) => x.key === key)
  if (!p) {
    state.appliedPreset = ''
    return
  }
  state.groupBy = p.group_by
  state.filters = JSON.parse(JSON.stringify(p.filters || []))
  state.appliedPreset = key
}

export function clearPreset() {
  state.filters = []
  state.appliedPreset = ''
}

export function removeFilter(idx) {
  state.filters.splice(idx, 1)
  state.appliedPreset = ''
}

// Agrega un filtro por atributo o por pregunta (`kind` = 'attribute' |
// 'question'). Una lista de valores se junta con la del filtro existente; un
// rango {min, max} reemplaza al anterior.
export function addFilter(kind, key, value) {
  const existing = state.filters.find((f) => f[kind] === key)
  if (!existing) {
    state.filters.push({ [kind]: key, value })
  } else if (Array.isArray(value) && typeof existing.value !== 'object') {
    // Los presets pueden traer un valor suelto en vez de una lista.
    existing.value = [...new Set([existing.value, ...value])]
  } else if (Array.isArray(value) && Array.isArray(existing.value)) {
    existing.value = [...new Set([...existing.value, ...value])]
  } else {
    existing.value = value
  }
  state.appliedPreset = ''
}

function buildBody() {
  return {
    question_id: state.questionId,
    filters: state.filters,
    group_by: state.groupBy,
    initial_only: state.initialOnly,
    wave_id: state.waveId || null,
  }
}

export async function runCurrentQuery() {
  if (!state.questionId) return
  state.loading = true
  state.error = null
  try {
    state.lastResult = await api.runQuery(buildBody())
  } catch (e) {
    state.lastResult = null
    state.error = e.message
  } finally {
    state.loading = false
  }
}

export function setQueryMode(mode) {
  state.queryMode = mode
}

export function toggleSidebar() {
  state.sidebarOpen = !state.sidebarOpen
}

// ── Chat history (localStorage) ────────────────────────────────────────────

let _msgSeq = 0
function msgId() {
  return (
    (crypto.randomUUID && crypto.randomUUID()) || `m${Date.now()}_${_msgSeq++}`
  )
}

function conversationTitle(messages) {
  const firstUser = messages.find((m) => m.role === 'user')
  const t = (firstUser?.text || 'Conversación').trim()
  return t.length > 48 ? t.slice(0, 48) + '…' : t
}

function persistConversations() {
  // Keep only the most recently updated conversations.
  state.conversations.sort((a, b) => b.updatedAt - a.updatedAt)
  if (state.conversations.length > MAX_CONVERSATIONS) {
    state.conversations.splice(MAX_CONVERSATIONS)
  }
  try {
    localStorage.setItem(CHAT_STORAGE_KEY, JSON.stringify(state.conversations))
  } catch (e) {
    console.error('No se pudo guardar el historial de chats:', e)
  }
}

export function loadConversations() {
  try {
    const raw = localStorage.getItem(CHAT_STORAGE_KEY)
    if (!raw) return
    const parsed = JSON.parse(raw)
    if (Array.isArray(parsed)) {
      state.conversations = parsed
        .filter((c) => c && c.id && Array.isArray(c.messages))
        .sort((a, b) => b.updatedAt - a.updatedAt)
        .slice(0, MAX_CONVERSATIONS)
    }
  } catch (e) {
    console.error('No se pudo leer el historial de chats:', e)
  }
}

// Snapshot the active chat into the conversation list and persist it.
function syncCurrentConversation() {
  if (!state.chatMessages.length) return
  const now = Date.now()
  let conv = state.conversations.find(
    (c) => c.id === state.currentConversationId,
  )
  if (!conv) {
    conv = {
      id: (crypto.randomUUID && crypto.randomUUID()) || String(now),
      createdAt: now,
      updatedAt: now,
      title: '',
      messages: [],
    }
    state.currentConversationId = conv.id
    state.conversations.unshift(conv)
  }
  conv.messages = JSON.parse(JSON.stringify(state.chatMessages))
  conv.title = conversationTitle(state.chatMessages)
  conv.updatedAt = now
  persistConversations()
}

export function newConversation() {
  state.chatMessages = []
  state.currentConversationId = null
}

export function loadConversation(id) {
  const conv = state.conversations.find((c) => c.id === id)
  if (!conv) return
  state.currentConversationId = id
  state.chatMessages = conv.messages.map((m) => ({ ...m, id: m.id || msgId() }))
}

export function deleteConversation(id) {
  const idx = state.conversations.findIndex((c) => c.id === id)
  if (idx === -1) return
  state.conversations.splice(idx, 1)
  if (state.currentConversationId === id) newConversation()
  persistConversations()
}

// Agrega un mensaje al historial de `convId`.
function appendToConversation(convId, message) {
  const conv = state.conversations.find((c) => c.id === convId)

  // Si borraron la conversación, descartar mensaje.
  if (!conv) return

  if (state.currentConversationId === convId) {
    // Si es la conversación activa, agregar el mensaje al chat.
    state.chatMessages.push(message)
    syncCurrentConversation()
    return
  }

  // Si no es la conversación activa, guardar el mensaje en el historial.
  conv.messages.push(JSON.parse(JSON.stringify(message)))
  conv.updatedAt = Date.now()
  persistConversations()
}

export async function sendChatMessage(text) {
  const msg = (text || '').trim()
  if (!msg || chatLoading.value) return

  // Tomar el historial de previos turnos (solo texto). Sirve como
  // contexto para futuras peticiones
  const history = state.chatMessages.map((m) => ({
    role: m.role,
    text: m.text,
  }))
  state.chatMessages.push({ id: msgId(), role: 'user', text: msg })
  syncCurrentConversation() // surface the conversation in the list right away

  // Se fija el convId desde el cual se hizo la petición.
  const convId = state.currentConversationId
  state.pendingChats.push(convId)
  try {
    const res = await api.chat({ message: msg, history })
    appendToConversation(convId, {
      id: msgId(),
      role: 'assistant',
      text: res.reply,
      data: res.data || null,
      toolCalls: res.tool_calls || [],
    })
  } catch (e) {
    appendToConversation(convId, {
      id: msgId(),
      role: 'assistant',
      text: `Lo siento, ocurrió un error.`,
      error: true,
    })
  } finally {
    const i = state.pendingChats.indexOf(convId)
    if (i !== -1) state.pendingChats.splice(i, 1)
  }
}

export async function retryLastMessage() {
  if (chatLoading.value) return
  const msgs = state.chatMessages
  if (msgs.length && msgs[msgs.length - 1].role === 'assistant') msgs.pop()
  if (!msgs.length || msgs[msgs.length - 1].role !== 'user') return
  const last = msgs.pop()
  syncCurrentConversation()
  await sendChatMessage(last.text)
}

export async function exportCurrentCSV() {
  if (!state.lastResult) return
  const blob = await api.exportCSV(buildBody())
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `encuesta_p${state.questionId}.csv`
  a.click()
  URL.revokeObjectURL(url)
}
