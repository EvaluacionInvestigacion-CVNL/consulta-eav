<script setup>
import { ref, nextTick, watch } from 'vue'
import { Send, Sparkles, RotateCw } from 'lucide-vue-next'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import {
  state,
  chatLoading,
  sendChatMessage,
  retryLastMessage,
  filterValueLabel,
} from '../store.js'
import ResultView from './ResultView.vue'

const input = ref('')
const scroller = ref(null)

// Markdown del asistente: negritas en cifras, listas cortas, `código` inline.
// `breaks: true` → un salto de línea simple es <br> (natural en chat). Se
// DESHABILITAN las tablas (el tokenizer devuelve undefined → caen a texto
// plano) para que no compitan con la tabla real de ResultView.
marked.use({ gfm: true, breaks: true, tokenizer: { table: () => undefined } })

// Los enlaces (raros, pero por si acaso) abren en pestaña nueva y sin opener.
DOMPurify.addHook('afterSanitizeAttributes', (node) => {
  if (node.tagName === 'A') {
    node.setAttribute('target', '_blank')
    node.setAttribute('rel', 'noopener noreferrer')
  }
})

// Whitelist estrecha: inline + listas + code. Sin tablas, encabezados, img ni
// nada que ejecute. DOMPurify es defensa en profundidad aunque el texto venga
// de nuestro propio modelo.
function renderMarkdown(text) {
  if (!text) return ''
  const html = marked.parse(String(text), { async: false })
  return DOMPurify.sanitize(html, {
    ALLOWED_TAGS: [
      'p',
      'br',
      'strong',
      'em',
      'b',
      'i',
      'ul',
      'ol',
      'li',
      'code',
      'pre',
      'a',
      'blockquote',
      'span',
    ],
    ALLOWED_ATTR: ['href', 'target', 'rel'],
  })
}

const suggestions = [
  '¿Qué porcentaje de personas se siente segura en su municipio?',
  'Compara la percepción de inseguridad entre hombres y mujeres',
  'Satisfacción con los servicios de salud por municipio',
]

async function submit() {
  const text = input.value
  if (!text.trim() || chatLoading.value) return
  input.value = ''
  await sendChatMessage(text)
}

function useSuggestion(s) {
  if (chatLoading.value) return
  input.value = s
  submit()
}

function toolSummary(calls) {
  if (!calls || !calls.length) return ''
  return calls
    .map((c) => {
      const y = c['año'] ? ` · ${c['año']}` : ''
      const g =
        !c.group_by || c.group_by === 'answer'
          ? ''
          : ` · agrupado por ${c.group_by}`
      const f =
        c.filters && c.filters.length
          ? ' · filtros: ' +
            c.filters
              .map((fl) => `${fl.attribute}=${filterValueLabel(fl)}`)
              .join(', ')
          : ''
      return `${c.question_id}${y}${g}${f}`
    })
    .join('  |  ')
}

// Autoscroll on new messages / loading state.
watch(
  () => [state.chatMessages.length, chatLoading.value],
  async () => {
    await nextTick()
    if (scroller.value) scroller.value.scrollTop = scroller.value.scrollHeight
  },
)
</script>

<template>
  <div class="flex-1 flex flex-col overflow-hidden bg-[#fcf0e4]">
    <!-- Messages -->
    <div ref="scroller" class="flex-1 overflow-auto p-4 md:p-8">
      <div class="max-w-4xl mx-auto space-y-6">
        <!-- Empty state -->
        <div
          v-if="!state.chatMessages.length"
          class="flex flex-col items-center justify-center text-center gap-4 mt-16"
        >
          <div class="bg-[#7e34c3]/10 rounded-full p-4">
            <Sparkles class="size-8 text-[#7e34c3]" />
          </div>
          <h3 class="font-['Manrope'] font-bold text-xl text-[#1e293b]">
            Pregúntale a la encuesta
          </h3>
          <p class="text-sm text-[#64748b] max-w-md">
            Escribe tu pregunta en lenguaje natural. La IA elige la pregunta de
            la encuesta, aplica filtros y agrupaciones, y te responde con cifras
            reales.
          </p>
          <div class="flex flex-col gap-2 mt-2 w-full max-w-md">
            <button
              v-for="s in suggestions"
              :key="s"
              @click="useSuggestion(s)"
              class="text-left text-sm text-[#475569] bg-white border border-[#e2e8f0] rounded-xl px-4 py-3 hover:border-[#7e34c3] hover:text-[#7e34c3] transition-colors"
            >
              {{ s }}
            </button>
          </div>
        </div>

        <!-- Conversation -->
        <template v-for="m in state.chatMessages" :key="m.id">
          <!-- User bubble -->
          <div v-if="m.role === 'user'" class="flex justify-end">
            <div
              class="max-w-[80%] bg-[#7e34c3] text-white rounded-2xl rounded-br-sm px-4 py-2.5 text-sm font-medium shadow-sm"
            >
              {{ m.text }}
            </div>
          </div>

          <!-- Assistant bubble -->
          <div v-else class="flex flex-col gap-3">
            <div
              class="max-w-[90%] bg-white border border-[#e2e8f0] rounded-2xl rounded-bl-sm px-4 py-3 text-sm leading-relaxed shadow-sm"
              :class="m.error ? 'text-[#b91c1c]' : 'text-[#1e293b]'"
            >
              <div class="md" v-html="renderMarkdown(m.text)"></div>
              <p
                v-if="m.toolCalls && m.toolCalls.length"
                class="mt-2 pt-2 border-t border-[#f1f5f9] text-[11px] text-[#94a3b8] font-mono"
              >
                {{ toolSummary(m.toolCalls) }}
              </p>
              <button
                v-if="m.error && !chatLoading"
                @click="retryLastMessage"
                class="mt-2 inline-flex items-center gap-1.5 text-xs font-semibold text-[#b91c1c] hover:text-[#7f1d1d] transition-colors"
              >
                <RotateCw class="size-3.5" />
                Reintentar
              </button>
            </div>

            <!-- Result for this answer (toggle table / chart) -->
            <div
              v-if="m.data"
              class="bg-white rounded-lg border border-[#e2e8f0] shadow-sm overflow-hidden"
            >
              <ResultView :data="m.data" />
            </div>
          </div>
        </template>

        <div v-if="chatLoading" class="flex flex-col gap-1.5">
          <div
            class="w-fit bg-white border border-[#e2e8f0] rounded-2xl rounded-bl-sm px-4 py-3 shadow-sm"
          >
            <div class="typing"><span></span><span></span><span></span></div>
          </div>
          <span class="text-xs text-[#94a3b8] pl-1"
            >Consultando la encuesta…</span
          >
        </div>
      </div>
    </div>

    <!-- Composer -->
    <div class="border-t border-[#e2e8f0] bg-white/70 backdrop-blur px-8 py-4">
      <form
        @submit.prevent="submit"
        class="max-w-4xl mx-auto flex items-end gap-3"
      >
        <textarea
          v-model="input"
          rows="1"
          placeholder="Escribe tu pregunta…"
          @keydown.enter.exact.prevent="submit"
          class="flex-1 resize-none bg-[#f1f5f9] border border-gray-300 rounded-2xl px-4 py-3 text-sm text-[#334155] focus:outline-none focus:border-[#7e34c3] max-h-40"
        ></textarea>
        <button
          type="submit"
          :disabled="!input.trim() || chatLoading"
          class="bg-[#7e34c3] hover:bg-[#5e2494] disabled:opacity-45 disabled:cursor-not-allowed text-white rounded-2xl px-5 py-3 flex items-center gap-2 font-bold shadow-lg shadow-[#7e34c3]/20 transition-colors shrink-0"
        >
          <Send class="size-4 justify-center" />
        </button>
      </form>
    </div>
  </div>
</template>

<style scoped>
/* Markdown del asistente. Tailwind v4 no trae el plugin typography, así que se
   estilan los elementos a mano. `:deep` porque el HTML viene de v-html. */
.md {
  white-space: normal;
}
.md :deep(p) {
  margin: 0;
}
.md :deep(p + p) {
  margin-top: 0.5rem;
}
.md :deep(strong),
.md :deep(b) {
  font-weight: 700;
  color: #0f172a;
}
.md :deep(em),
.md :deep(i) {
  font-style: italic;
}
.md :deep(ul),
.md :deep(ol) {
  margin: 0.375rem 0;
  padding-left: 1.25rem;
}
.md :deep(ul) {
  list-style: disc;
}
.md :deep(ol) {
  list-style: decimal;
}
.md :deep(li) {
  margin: 0.125rem 0;
}
.md :deep(li::marker) {
  color: #94a3b8;
}
.md :deep(code) {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 0.85em;
  background: #f1f5f9;
  color: #7e34c3;
  padding: 0.1em 0.35em;
  border-radius: 0.3rem;
}
.md :deep(pre) {
  background: #f1f5f9;
  padding: 0.6rem 0.8rem;
  border-radius: 0.5rem;
  overflow-x: auto;
  margin: 0.5rem 0;
}
.md :deep(pre code) {
  background: none;
  color: #334155;
  padding: 0;
}
.md :deep(a) {
  color: #7e34c3;
  text-decoration: underline;
}
.md :deep(blockquote) {
  border-left: 3px solid #e2e8f0;
  padding-left: 0.75rem;
  color: #475569;
  margin: 0.5rem 0;
}

.typing {
  display: flex;
  align-items: center;
  gap: 4px;
}
.typing span {
  width: 7px;
  height: 7px;
  border-radius: 9999px;
  background: #7e34c3;
  opacity: 0.4;
  animation: typing-bounce 1.2s infinite ease-in-out;
}
.typing span:nth-child(2) {
  animation-delay: 0.15s;
}
.typing span:nth-child(3) {
  animation-delay: 0.3s;
}
@keyframes typing-bounce {
  0%,
  60%,
  100% {
    transform: translateY(0);
    opacity: 0.4;
  }
  30% {
    transform: translateY(-4px);
    opacity: 1;
  }
}
</style>
