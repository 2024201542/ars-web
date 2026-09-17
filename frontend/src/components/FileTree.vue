<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { useWorkspaceStore } from '@/stores/workspace'
import { toast } from '@/composables/useToast'
import { api } from '@/api'
import {
  FolderTree, Upload, Trash2, RefreshCw, Loader2,
  FileText, FileCode, Table2, Image, File,
  ChevronRight, ChevronDown, FolderOpen, Folder,
} from 'lucide-vue-next'

const props = defineProps<{ sessionId: string; collapsed?: boolean }>()
const emit = defineEmits<{ select: [file: any]; toggle: [] }>()
const selectedPath = defineModel<string | null>('selectedPath', { default: null })

const store = useWorkspaceStore()
const uploading = ref(false)
const expandedDirs = ref<Set<string>>(new Set([''])) // root always expanded

// ── 构建目录树 ──

interface TreeNode {
  name: string
  path: string
  isDir: boolean
  children: TreeNode[]
  file?: any // the original file object for leaf nodes
}

const tree = computed(() => {
  const root: TreeNode = { name: '', path: '', isDir: true, children: [] }
  const dirs = new Map<string, TreeNode>()
  dirs.set('', root)

  for (const f of store.files) {
    const dir = f.dir || ''
    // ensure parent dirs exist
    const parts = dir.split('/').filter(Boolean)
    let parentPath = ''
    for (const part of parts) {
      const full = parentPath ? `${parentPath}/${part}` : part
      if (!dirs.has(full)) {
        const node: TreeNode = { name: part, path: full, isDir: true, children: [] }
        dirs.set(full, node)
        const parent = dirs.get(parentPath)
        if (parent) parent.children.push(node)
      }
      parentPath = full
    }
    const parent = dirs.get(dir)
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

function toggleDir(dirPath: string) {
  if (expandedDirs.value.has(dirPath)) {
    expandedDirs.value.delete(dirPath)
  } else {
    expandedDirs.value.add(dirPath)
  }
}

async function doUpload(e: Event) {
  const f = (e.target as HTMLInputElement).files?.[0]
  if (!f) return
  uploading.value = true
  try {
    await store.upload(props.sessionId, f)
    toast.success(`已上传: ${f.name}`)
  } catch (ex: any) {
    toast.error('上传失败: ' + (ex.message || ''))
  } finally {
    uploading.value = false
  }
}

async function handleDelete(filePath: string, e: Event) {
  e.stopPropagation()
  try { await store.remove(props.sessionId, filePath) } catch { toast.error('删除失败') }
}

async function handleRefresh() {
  await store.refresh(props.sessionId)
}

watch(() => props.sessionId, (id) => {
  if (id) store.loadFiles(id)
}, { immediate: true })

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
  return `${(bytes / (1024*1024)).toFixed(1)} MB`
}
</script>

<template>
  <!-- 折叠态：窄条 -->
  <template v-if="props.collapsed">
    <div class="flex flex-col h-full w-full items-center pt-3 gap-3">
      <button @click="emit('toggle')" class="text-ruc-text-light hover:text-ruc-red transition-colors p-1" title="展开文件树">
        <FolderTree class="w-4 h-4" />
      </button>
      <span class="text-[10px] font-ui text-ruc-text-light writing-vertical">{{ store.files.length }}</span>
      <label class="cursor-pointer text-ruc-text-light hover:text-ruc-red transition-colors p-1" title="上传文件">
        <Loader2 v-if="uploading" class="w-3.5 h-3.5 animate-spin" />
        <Upload v-else class="w-3.5 h-3.5" />
        <input type="file" class="hidden" @change="doUpload" />
      </label>
    </div>
  </template>

  <!-- 展开态 -->
  <template v-else>
  <div class="flex flex-col h-full">
    <div class="flex items-center justify-between px-3 py-2 border-b border-ruc-divider flex-shrink-0">
      <span class="text-xs font-ui font-medium text-ruc-text-dim flex items-center gap-1.5">
        <FolderTree class="w-3.5 h-3.5" />
        项目文件
      </span>
      <div class="flex items-center gap-0.5">
        <button @click="handleRefresh" class="p-1 text-ruc-text-dim hover:text-ruc-red rounded transition-colors" title="刷新">
          <RefreshCw class="w-3.5 h-3.5" :class="{ 'animate-spin': store.loading }" />
        </button>
        <label class="p-1 cursor-pointer text-ruc-text-dim hover:text-ruc-red rounded transition-colors" title="上传文件">
          <Loader2 v-if="uploading" class="w-3.5 h-3.5 animate-spin" />
          <Upload v-else class="w-3.5 h-3.5" />
          <input type="file" class="hidden" @change="doUpload" />
        </label>
      </div>
    </div>

    <!-- Tree -->
    <div class="flex-1 overflow-y-auto py-1 text-xs font-ui">
      <template v-for="node in tree.children" :key="node.path">
        <!-- Directory -->
        <template v-if="node.isDir">
          <div
            @click="toggleDir(node.path)"
            class="flex items-center gap-1 px-2 py-1 cursor-pointer text-ruc-text-dim hover:text-ruc-text hover:bg-ruc-warm transition-colors"
          >
            <component :is="expandedDirs.has(node.path) ? ChevronDown : ChevronRight" class="w-3 h-3 flex-shrink-0" />
            <component :is="expandedDirs.has(node.path) ? FolderOpen : Folder" class="w-3.5 h-3.5 flex-shrink-0" />
            <span class="truncate">{{ node.name }}</span>
          </div>
          <!-- Children -->
          <template v-if="expandedDirs.has(node.path)">
            <div
              v-for="child in node.children"
              :key="child.path"
              @click="!child.isDir && (selectedPath = child.path) && emit('select', child.file)"
              class="flex items-center gap-1 px-2 py-1 cursor-pointer transition-colors group"
              :class="[
                child.isDir ? '' : 'pl-6',
                !child.isDir && selectedPath === child.path
                  ? 'active-left'
                  : 'border-l-[3px] border-transparent text-ruc-text-dim hover:bg-ruc-warm hover:text-ruc-text'
              ]"
            >
              <component :is="child.isDir ? Folder : fileIcon(child.file?.ext || '')" class="w-3.5 h-3.5 flex-shrink-0" />
              <span class="truncate flex-1">{{ child.name }}</span>
              <span class="text-[10px] text-ruc-text-light flex-shrink-0 hidden group-hover:inline">
                {{ child.file ? fmtSize(child.file.size_bytes) : '' }}
              </span>
            </div>
          </template>
        </template>
        <!-- Root-level file -->
        <template v-else>
          <div
            @click="selectedPath = node.path; emit('select', node.file)"
            class="flex items-center gap-1 px-2 py-1 cursor-pointer transition-colors group"
            :class="[
              selectedPath === node.path
                ? 'active-left'
                : 'border-l-[3px] border-transparent text-ruc-text-dim hover:bg-ruc-warm hover:text-ruc-text'
            ]"
          >
            <component :is="fileIcon(node.file?.ext || '')" class="w-3.5 h-3.5 flex-shrink-0" />
            <span class="truncate flex-1">{{ node.name }}</span>
            <span class="text-[10px] text-ruc-text-light flex-shrink-0 hidden group-hover:inline">
              {{ node.file ? fmtSize(node.file.size_bytes) : '' }}
            </span>
            <button
              @click="(e: MouseEvent) => handleDelete(node.path, e)"
              class="opacity-0 group-hover:opacity-100 flex-shrink-0 p-0.5 text-ruc-text-dim hover:text-ruc-error rounded transition-all"
              title="删除"
            >
              <Trash2 class="w-3 h-3" />
            </button>
          </div>
        </template>
      </template>

      <!-- Empty -->
      <div v-if="tree.children.length === 0 && !store.loading" class="px-3 py-8 text-center">
        <File class="w-6 h-6 mx-auto text-ruc-border-ruc-divider mb-2" />
        <p class="text-ruc-text-light text-xs">上传文件或等待 Agent 生成</p>
      </div>
    </div>

    <!-- Footer -->
    <div class="px-3 py-1.5 border-t border-ruc-divider flex-shrink-0 flex items-center justify-between">
      <span class="text-[10px] text-ruc-text-light font-ui">{{ store.files.length }} 个文件</span>
      <span v-if="store.loading" class="text-[10px] text-ruc-text-light font-ui">同步中…</span>
    </div>
  </div>
  </template>
</template>
