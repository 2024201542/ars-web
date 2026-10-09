<script setup lang="ts">
import { ref, computed, watch, nextTick } from 'vue'
import { useWorkspaceStore } from '@/stores/workspace'
import { toast } from '@/composables/useToast'
import {
  FolderTree, Upload, FolderOpen, Folder, RefreshCw, Loader2, File, PanelLeftClose,
  ChevronRight, ChevronDown, Trash2, FileText, FileCode, Table2, Image, FilePlus, FolderPlus, Pencil,
} from 'lucide-vue-next'

const FILE_KINDS = [
  { id: 'draft', label: '文稿' },
  { id: 'outline', label: '大纲' },
  { id: 'notes', label: '读书笔记' },
  { id: 'bib', label: '参考文献' },
  { id: 'text', label: '纯文本' },
]

const props = defineProps<{ sessionId: string; collapsed?: boolean; beforeLeave?: () => Promise<boolean> }>()
const emit = defineEmits<{ select: [file: any]; toggle: []; collapse: []; removed: [path: string] }>()
const selectedPath = defineModel<string | null>('selectedPath', { default: null })

const store = useWorkspaceStore()
const uploading = ref(false)
const picking = ref(false)
const creating = ref(false)
const newMenu = ref(false)
const dirMenu = ref(false)
const dirName = ref('')
const dirInput = ref<HTMLInputElement | null>(null)
const activeDir = ref('')
const fileCount = computed(() => store.files.filter((f) => !f.is_dir).length)
const actionsOpen = computed(() => newMenu.value || dirMenu.value)
const panelHot = ref(false)
const renamingPath = ref('')
const renameValue = ref('')
const createHint = computed(() => {
  if (store.source === 'local') return activeDir.value || '最上面，跟现有文件夹并列'
  if (activeDir.value.startsWith('uploads')) return activeDir.value
  return 'uploads'
})
const expandedDirs = ref<Set<string>>(new Set(['', 'generated', 'uploads']))

// ── 构建目录树 ──

interface TreeNode {
  name: string
  path: string
  isDir: boolean
  children: TreeNode[]
  file?: any
  placeholder?: boolean
}

const tree = computed(() => {
  const root: TreeNode = { name: '', path: '', isDir: true, children: [] }
  const dirs = new Map<string, TreeNode>()
  dirs.set('', root)

  function ensureChain(full: string) {
    const parts = full.split('/').filter(Boolean)
    let parentPath = ''
    for (const part of parts) {
      const path = parentPath ? `${parentPath}/${part}` : part
      if (!dirs.has(path)) {
        const node: TreeNode = { name: part, path, isDir: true, children: [] }
        dirs.set(path, node)
        dirs.get(parentPath)?.children.push(node)
      }
      parentPath = path
    }
  }

  for (const f of store.files) {
    if (f.is_dir) {
      ensureChain(f.path || f.name)
      continue
    }
    ensureChain(f.dir || '')
    const parent = dirs.get(f.dir || '')
    if (parent) {
      parent.children.push({ name: f.name, path: f.path, isDir: false, children: [], file: f })
    }
  }

  // sort: dirs first, then files, alphabetically
  function sortNode(node: TreeNode) {
    node.children.sort((a, b) => {
      if (a.isDir && !b.isDir) return -1
      if (!a.isDir && b.isDir) return 1
      return a.name.localeCompare(b.name)
    })
    node.children.forEach(sortNode)
  }
  sortNode(root)
  return root
})

const rows = computed(() => {
  const out: { node: TreeNode; depth: number }[] = []
  function walk(nodes: TreeNode[], depth: number) {
    for (const node of nodes) {
      out.push({ node, depth })
      if (node.isDir && expandedDirs.value.has(node.path)) {
        if (!node.children.length) {
          out.push({
            node: { name: '空文件夹', path: `${node.path}/\0empty`, isDir: false, children: [], placeholder: true },
            depth: depth + 1,
          })
        } else {
          walk(node.children, depth + 1)
        }
      }
    }
  }
  walk(tree.value.children, 0)
  return out
})

function fileIcon(ext: string) {
  const e = (ext || '').toLowerCase()
  if (['.md', '.txt'].includes(e)) return FileText
  if (['.py', '.r', '.js', '.ts', '.sh'].includes(e)) return FileCode
  if (['.csv', '.tsv', '.xlsx', '.xls'].includes(e)) return Table2
  if (['.png', '.jpg', '.jpeg', '.svg', '.gif', '.webp'].includes(e)) return Image
  return File
}

function fmtSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function toggleDir(dirPath: string) {
  if (expandedDirs.value.has(dirPath)) {
    expandedDirs.value.delete(dirPath)
  } else {
    expandedDirs.value.add(dirPath)
  }
}

async function uploadOne(file: File) {
  const rel = store.source === 'local' && activeDir.value ? `${activeDir.value}/${file.name}` : file.name
  await store.upload(props.sessionId, file, rel)
  if (store.source === 'site') expandedDirs.value.add('uploads')
  if (activeDir.value) expandedDirs.value.add(activeDir.value)
}

async function doUpload(e: Event) {
  const input = e.target as HTMLInputElement
  const f = input.files?.[0]
  input.value = ''
  if (!f || needFolder()) return
  uploading.value = true
  try {
    await uploadOne(f)
    toast.success(`已放入: ${f.name}`)
  } catch (ex: any) {
    toast.error('上传失败: ' + (ex.message || ''))
  } finally {
    uploading.value = false
  }
}

async function onTreeDrop(e: DragEvent) {
  const files = Array.from(e.dataTransfer?.files || [])
  if (!files.length || needFolder()) return
  e.preventDefault()
  uploading.value = true
  try {
    for (const file of files) await uploadOne(file)
    toast.success(files.length > 1 ? `已放入 ${files.length} 个文件` : `已放入: ${files[0].name}`)
  } catch (ex: any) {
    toast.error('上传失败: ' + (ex.message || ''))
  } finally {
    uploading.value = false
  }
}

async function pickFolder() {
  if (picking.value) return
  if (props.beforeLeave && !(await props.beforeLeave())) return
  picking.value = true
  newMenu.value = false
  dirMenu.value = false
  toast.info('请在弹出的窗口里选择文件夹')
  try {
    const info = await store.openFolder(props.sessionId)
    if (info.cancelled) toast.info('没有选择文件夹')
    else toast.success(`已打开 ${info.label || '文件夹'}`)
  } catch (ex: any) {
    toast.error(ex.message || '打开文件夹失败')
  } finally {
    picking.value = false
  }
}

function needFolder() {
  if (store.source === 'local') return false
  toast.info('先选择一个文件夹。对话留在这个账号里。')
  return true
}

function parentDir(path: string) {
  const index = path.lastIndexOf('/')
  return index < 0 ? '' : path.slice(0, index)
}

const activeName = computed(() => {
  if (!activeDir.value) return store.rootLabel || '最上面'
  const index = activeDir.value.lastIndexOf('/')
  return index < 0 ? activeDir.value : activeDir.value.slice(index + 1)
})

function placeDirectory(where: 'inside' | 'sibling' = 'inside') {
  if (store.source !== 'local') return activeDir.value.startsWith('uploads') ? activeDir.value : ''
  if (where === 'sibling') return parentDir(activeDir.value)
  return activeDir.value
}

function selectDir(path: string) {
  activeDir.value = path
  toggleDir(path)
}

async function createDir(where: 'inside' | 'sibling' = 'sibling') {
  const name = dirName.value.trim()
  if (!name || creating.value || needFolder()) return
  creating.value = true
  try {
    const directory = placeDirectory(where)
    const info = await store.createDirectory(props.sessionId, name, directory)
    if (directory) expandedDirs.value.add(directory)
    if (info?.dir) expandedDirs.value.add(info.dir)
    if (info?.path) expandedDirs.value.add(info.path)
    dirName.value = ''
    dirMenu.value = false
    toast.success(`已新建文件夹 ${info?.name || name}`)
  } catch (ex: any) {
    toast.error(ex.message || '新建文件夹失败')
  } finally {
    creating.value = false
  }
}

function openNewMenu() {
  dirMenu.value = false
  newMenu.value = !newMenu.value
}

function openDirMenu() {
  newMenu.value = false
  dirMenu.value = !dirMenu.value
  if (dirMenu.value) {
    dirName.value = ''
    nextTick(() => dirInput.value?.focus())
  }
}

async function createKind(kind: string) {
  if (creating.value || needFolder()) return
  newMenu.value = false
  creating.value = true
  try {
    const directory = placeDirectory()
    const file = await store.createFile(props.sessionId, kind, directory)
    if (file?.dir) expandedDirs.value.add(file.dir)
    if (file?.path) {
      selectedPath.value = file.path
      emit('select', file)
    }
    toast.success(`已新建 ${file?.name || '文件'}`)
  } catch (ex: any) {
    toast.error(ex.message || '新建失败')
  } finally {
    creating.value = false
  }
}

function startRename(file: any, event: MouseEvent) {
  event.stopPropagation()
  renamingPath.value = file.path
  renameValue.value = file.name
}

async function saveRename(file: any) {
  const name = renameValue.value.trim()
  if (!name || name === file.name) {
    renamingPath.value = ''
    return
  }
  try {
    const updated = await store.rename(props.sessionId, file.path, name)
    renamingPath.value = ''
    if (selectedPath.value === file.path && updated?.path) {
      selectedPath.value = updated.path
      emit('select', updated)
    }
  } catch (ex: any) {
    toast.error(ex.message || '改名失败')
  }
}

function folderHasContents(path: string) {
  const prefix = `${path}/`
  return store.files.some((item) => item.path.startsWith(prefix))
}

async function handleDelete(filePath: string, e: Event, isDir = false) {
  e.stopPropagation()
  const name = filePath.split('/').pop() || filePath
  if (isDir && folderHasContents(filePath) && !window.confirm(`删除文件夹「${name}」，里面的文件会一起删掉。`)) return
  try {
    await store.remove(props.sessionId, filePath)
    if (activeDir.value === filePath || activeDir.value.startsWith(`${filePath}/`)) activeDir.value = parentDir(filePath)
    if (selectedPath.value === filePath || (selectedPath.value || '').startsWith(`${filePath}/`)) selectedPath.value = null
    emit('removed', filePath)
    if (isDir) toast.success(`已删除文件夹 ${name}`)
  } catch (ex: any) {
    toast.error(ex.message || '删除失败')
  }
}

async function handleRefresh() {
  await store.refresh(props.sessionId)
}

watch(() => props.sessionId, (id) => {
  if (id) store.loadFiles(id)
}, { immediate: true })

function onFileDragStart(e: DragEvent, file: any) {
  if (!file || !e.dataTransfer) return
  e.dataTransfer.effectAllowed = 'copy'
  e.dataTransfer.setData('application/x-ars-file', JSON.stringify(file))
  e.dataTransfer.setData('text/plain', file.name || '')
}
</script>

<template>
  <!-- 折叠态：窄条 -->
  <template v-if="props.collapsed">
    <div class="flex flex-col h-full w-full items-center pt-3 gap-3">
      <button @click="emit('toggle')" class="text-ruc-text-light hover:text-ruc-red transition-colors p-1" title="展开文件树">
        <FolderTree class="w-4 h-4" />
      </button>
      <span class="text-[10px] font-ui text-ruc-text-light writing-vertical">{{ fileCount }}</span>
      <button class="text-ruc-text-light hover:text-ruc-red transition-colors p-1" title="选择文件夹" @click="pickFolder">
        <FolderOpen class="w-3.5 h-3.5" />
      </button>
      <label class="cursor-pointer text-ruc-text-light hover:text-ruc-red transition-colors p-1" title="上传文件，含 Word（.docx）">
        <Loader2 v-if="uploading" class="w-3.5 h-3.5 animate-spin" />
        <Upload v-else class="w-3.5 h-3.5" />
        <input type="file" class="hidden" accept=".docx,.doc,.pdf,.txt,.md,.tex,.bib,.png,.jpg,.jpeg,.xlsx,.xls,.csv" @change="doUpload" />
      </label>
    </div>
  </template>

  <!-- 展开态 -->
  <template v-else>
  <div
    class="flex flex-col h-full"
    @mouseenter="panelHot = true"
    @mouseleave="panelHot = false"
    @click="newMenu = false; dirMenu = false"
    @dragover.prevent
    @drop="onTreeDrop"
  >
    <div class="border-b border-ruc-divider flex-shrink-0" @click.stop>
      <div class="flex items-center gap-1 px-3 pt-2 pb-1">
        <button
          type="button"
          class="min-w-0 flex-1 text-left text-sm font-ui font-bold truncate rounded px-1 py-0.5"
          :class="activeDir === '' ? 'bg-ruc-warm text-ruc-text' : 'text-ruc-text-dim hover:bg-ruc-warm'"
          :title="store.rootPath || '点这里，新建文件夹会跟现有文件夹并列'"
          @click="activeDir = ''"
        >
          {{ store.rootLabel || '项目文件' }}
        </button>
        <button class="p-1 flex-shrink-0 text-ruc-text-dim hover:text-ruc-red rounded transition-colors" title="选择文件夹" @click="pickFolder">
          <Loader2 v-if="picking" class="w-3.5 h-3.5 animate-spin" />
          <FolderOpen v-else class="w-3.5 h-3.5" />
        </button>
      </div>
      <div v-show="panelHot || actionsOpen" class="flex items-center justify-end px-2 pb-1">
        <button @click="handleRefresh" class="p-1 text-ruc-text-dim hover:text-ruc-red rounded transition-colors" title="刷新">
          <RefreshCw class="w-3.5 h-3.5" :class="{ 'animate-spin': store.loading }" />
        </button>
        <div class="relative">
          <button class="p-1 text-ruc-text-dim hover:text-ruc-red rounded transition-colors" title="新建文件" @click.stop="openNewMenu">
            <Loader2 v-if="creating && !dirMenu" class="w-3.5 h-3.5 animate-spin" />
            <FilePlus v-else class="w-3.5 h-3.5" />
          </button>
          <div v-if="newMenu" class="absolute right-0 top-full mt-1 z-30 w-36 bg-white border border-ruc-divider rounded-xl shadow-modal py-1" @click.stop>
            <p class="px-3 py-1 text-[10px] text-ruc-text-light">新建到 {{ createHint }}</p>
            <button
              v-for="kind in FILE_KINDS"
              :key="kind.id"
              class="w-full text-left px-3 py-1.5 text-xs font-ui text-ruc-text hover:bg-ruc-red-pale hover:text-ruc-red"
              @click="createKind(kind.id)"
            >{{ kind.label }}</button>
          </div>
        </div>
        <div class="relative">
          <button class="p-1 text-ruc-text-dim hover:text-ruc-red rounded transition-colors" title="新建文件夹" @click.stop="openDirMenu">
            <FolderPlus class="w-3.5 h-3.5" />
          </button>
          <div v-if="dirMenu" class="absolute right-0 top-full mt-1 z-30 w-52 bg-white border border-ruc-divider rounded-xl shadow-modal p-2" @click.stop>
            <p class="px-1 pb-1 text-[10px] text-ruc-text-light leading-snug">{{ activeDir ? `当前点中的是「${activeName}」` : '当前在最上面，新文件夹会跟现有文件夹并列' }}</p>
            <input
              ref="dirInput"
              v-model="dirName"
              class="w-full text-xs px-2 py-1 rounded-lg border border-ruc-border focus:outline-none focus:border-ruc-red"
              placeholder="文件夹名称"
              @keydown.enter="createDir(activeDir ? 'sibling' : 'inside')"
              @keydown.esc="dirMenu = false"
            />
            <button
              class="mt-1.5 w-full text-xs font-ui py-1 rounded-lg bg-ruc-red text-white hover:bg-ruc-red-dark disabled:opacity-50"
              :disabled="!dirName.trim() || creating"
              @click="createDir(activeDir ? 'sibling' : 'inside')"
            >{{ activeDir ? `跟「${activeName}」并列` : '建在最上面' }}</button>
            <button
              v-if="activeDir"
              class="mt-1 w-full text-xs font-ui py-1 rounded-lg text-ruc-text-dim hover:text-ruc-red hover:bg-ruc-warm disabled:opacity-50"
              :disabled="!dirName.trim() || creating"
              @click="createDir('inside')"
            >放进「{{ activeName }}」里面</button>
          </div>
        </div>
        <label class="p-1 cursor-pointer text-ruc-text-dim hover:text-ruc-red rounded transition-colors" title="上传文件，含 Word（.docx）">
          <Loader2 v-if="uploading" class="w-3.5 h-3.5 animate-spin" />
          <Upload v-else class="w-3.5 h-3.5" />
          <input type="file" class="hidden" accept=".docx,.doc,.pdf,.txt,.md,.tex,.bib,.png,.jpg,.jpeg,.xlsx,.xls,.csv" @change="doUpload" />
        </label>
        <button @click="emit('collapse')" class="p-1 text-ruc-text-dim hover:text-ruc-red rounded transition-colors" title="收起文件">
          <PanelLeftClose class="w-3.5 h-3.5" />
        </button>
      </div>
    </div>

    <!-- Tree -->
    <div class="flex-1 overflow-y-auto py-1 text-xs font-ui">
      <template v-for="row in rows" :key="row.node.path">
        <div
          v-if="row.node.isDir"
          role="button"
          class="group flex items-center gap-1 py-1 cursor-pointer font-medium text-ruc-text-dim hover:bg-ruc-warm"
          :class="activeDir === row.node.path ? 'bg-ruc-warm text-ruc-text' : ''"
          :style="{ paddingLeft: (8 + row.depth * 12) + 'px' }"
          @click="selectDir(row.node.path)"
        >
          <component
            :is="expandedDirs.has(row.node.path) ? ChevronDown : ChevronRight"
            class="w-3 h-3 flex-shrink-0 text-ruc-text-light"
          />
          <component :is="expandedDirs.has(row.node.path) ? FolderOpen : Folder" class="w-3.5 h-3.5 flex-shrink-0 text-ruc-gold" />
          <span class="truncate flex-1">{{ row.node.name }}</span>
          <button
            class="opacity-0 group-hover:opacity-100 flex-shrink-0 p-0.5 text-ruc-text-dim hover:text-ruc-error rounded"
            title="删除"
            @click="(e: MouseEvent) => handleDelete(row.node.path, e, true)"
          >
            <Trash2 class="w-3 h-3" />
          </button>
        </div>
        <div
          v-else-if="row.node.placeholder"
          class="py-1 text-[10px] text-ruc-text-light"
          :style="{ paddingLeft: (8 + row.depth * 12) + 'px' }"
        >空文件夹</div>
        <div
          v-else
          draggable="true"
          role="button"
          class="flex items-center gap-1 py-1 cursor-pointer transition-colors group"
          :style="{ paddingLeft: (8 + row.depth * 12) + 'px' }"
          title="拖到右侧对话框即可引用"
          :class="selectedPath === row.node.path
            ? 'active-left'
            : 'border-l-[3px] border-transparent text-ruc-text-light hover:bg-ruc-warm hover:text-ruc-text-dim'"
          @dragstart="onFileDragStart($event, row.node.file)"
          @click="selectedPath = row.node.path; emit('select', row.node.file)"
        >
          <component :is="fileIcon(row.node.file?.ext || '')" class="w-3.5 h-3.5 flex-shrink-0" />
          <input
            v-if="renamingPath === row.node.path"
            v-model="renameValue"
            class="flex-1 min-w-0 text-xs px-1 py-0.5 rounded border border-ruc-red/30 focus:outline-none"
            @click.stop
            @keydown.enter="saveRename(row.node.file)"
            @keydown.esc="renamingPath = ''"
          />
          <span v-else class="truncate flex-1">{{ row.node.name }}</span>
          <span class="text-[10px] text-ruc-text-light flex-shrink-0 hidden group-hover:inline">
            {{ row.node.file ? fmtSize(row.node.file.size_bytes) : '' }}
          </span>
          <button
            class="opacity-0 group-hover:opacity-100 flex-shrink-0 p-0.5 text-ruc-text-dim hover:text-ruc-red rounded"
            title="改名"
            @click="startRename(row.node.file, $event)"
          >
            <Pencil class="w-3 h-3" />
          </button>
          <button
            class="opacity-0 group-hover:opacity-100 flex-shrink-0 p-0.5 text-ruc-text-dim hover:text-ruc-error rounded"
            title="删除"
            @click="(e: MouseEvent) => handleDelete(row.node.path, e)"
          >
            <Trash2 class="w-3 h-3" />
          </button>
        </div>
      </template>

      <div v-if="tree.children.length === 0 && !store.loading" class="px-3 py-8 text-center">
        <File class="w-6 h-6 mx-auto text-ruc-border mb-2" />
        <p class="text-ruc-text-light text-xs">先选择一个文件夹。对话留在这个账号里，文件放在这个文件夹里。</p>
      </div>
    </div>

    <!-- Footer -->
    <div class="px-3 py-1.5 border-t border-ruc-divider flex-shrink-0 flex items-center justify-between">
      <span class="text-[10px] text-ruc-text-light font-ui">{{ fileCount }} 个文件</span>
      <span v-if="store.truncated" class="text-[10px] text-ruc-text-light font-ui">只列出一部分</span>
      <span v-else-if="store.loading" class="text-[10px] text-ruc-text-light font-ui">同步中…</span>
    </div>
  </div>
  </template>
</template>
