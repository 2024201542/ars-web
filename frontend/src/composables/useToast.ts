import { ref, type Ref } from 'vue'

export interface Toast {
  id: number
  message: string
  type: 'success' | 'error' | 'warning' | 'info'
}

const _toasts: Ref<Toast[]> = ref([])
export { _toasts as toasts }

let nextId = 1

function showToast(message: string, type: Toast['type'] = 'info') {
  const id = nextId++
  _toasts.value.push({ id, message, type })
  setTimeout(() => {
    removeToast(id)
  }, 3000)
}

function removeToast(id: number) {
  const index = _toasts.value.findIndex(t => t.id === id)
  if (index > -1) {
    _toasts.value.splice(index, 1)
  }
}

const toastApi = {
  success: (msg: string) => showToast(msg, 'success'),
  error: (msg: string) => showToast(msg, 'error'),
  warning: (msg: string) => showToast(msg, 'warning'),
  info: (msg: string) => showToast(msg, 'info'),
  remove: removeToast,
}
export { toastApi as toast }

/** 组件中通过 `const toast = useToast()` 使用，也可直接 `import { toast }` */
export function useToast() {
  return toastApi
}
