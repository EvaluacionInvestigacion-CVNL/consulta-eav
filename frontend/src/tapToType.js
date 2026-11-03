import { ref, onMounted, onBeforeUnmount } from 'vue'
import { isMobile } from './store.js'

export function useTapToType(root) {
  const open = ref(false)
  const focused = ref(false)
  const typing = () => focused.value || !isMobile()

  function onTouchStart(e) {
    if (focused.value || open.value) return
    e.preventDefault()
    open.value = true
  }

  function onClick() {
    open.value = true
  }

  function onFocus() {
    focused.value = true
    open.value = true
  }

  function onBlur() {
    focused.value = false
    open.value = false
  }

  function closeOnOutside(e) {
    if (open.value && root.value && !root.value.contains(e.target))
      open.value = false
  }
  onMounted(() => document.addEventListener('pointerdown', closeOnOutside))
  onBeforeUnmount(() =>
    document.removeEventListener('pointerdown', closeOnOutside),
  )

  return { open, typing, onTouchStart, onClick, onFocus, onBlur }
}
