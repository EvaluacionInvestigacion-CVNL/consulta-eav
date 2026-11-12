<script setup>
import { ref } from 'vue'
import { Info } from 'lucide-vue-next'

defineProps({ text: { type: String, default: '' } })

const anchor = ref(null)
const show = ref(false)
const pos = ref({ top: 0, left: 0 })
const above = ref(false)

function open() {
  const el = anchor.value
  if (!el) return
  const r = el.getBoundingClientRect()
  // Flip above the icon when there isn't enough room below.
  above.value = window.innerHeight - r.bottom < 120
  pos.value = {
    top: above.value ? r.top - 8 : r.bottom + 8,
    left: r.left + r.width / 2,
  }
  show.value = true
}

function close() {
  show.value = false
}
</script>

<template>
  <span
    ref="anchor"
    @mouseenter="open"
    @mouseleave="close"
    @click.stop
    class="shrink-0 flex text-faint hover:text-brand cursor-help"
    aria-label="Información de la pregunta"
  >
    <Info class="size-4" />
  </span>
  <Teleport to="body">
    <div
      v-if="show && text"
      :style="{ top: pos.top + 'px', left: pos.left + 'px' }"
      class="fixed z-60 max-w-xs px-3 py-2 rounded-lg bg-ink text-white text-xs leading-snug shadow-xl pointer-events-none whitespace-pre-line"
      :class="above ? '-translate-x-1/2 -translate-y-full' : '-translate-x-1/2'"
    >
      {{ text }}
    </div>
  </Teleport>
</template>
