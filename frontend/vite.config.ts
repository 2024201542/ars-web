import { defineConfig, type Plugin } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'path'
import fs from 'fs'

const APP_BASE = process.env.VITE_APP_BASE || '/'

/**
 * pdfjs 解码 JBIG2 / JPEG2000 / ICC 需要 WASM 资源。
 * 默认不会打进产物，缺了就会出现
 *   "#instantiateWasm: Ensure that the `wasmUrl` API parameter is provided"
 *   "Jbig2Error: JBig2 failed to initialize"
 * 于是整页解不出图、扫描件预览一片空白。这里把它拷到 <base>/pdfjs/wasm/。
 */
function pdfjsWasm(): Plugin {
  const source = path.resolve(__dirname, 'node_modules/pdfjs-dist/wasm')
  return {
    name: 'pdfjs-wasm-assets',
    generateBundle() {
      if (!fs.existsSync(source)) {
        this.warn(`pdfjs wasm 目录不存在：${source}`)
        return
      }
      const target = path.resolve(__dirname, 'dist', 'pdfjs', 'wasm')
      fs.mkdirSync(target, { recursive: true })
      let copied = 0
      for (const entry of fs.readdirSync(source)) {
        if (!entry.endsWith('.wasm') && !entry.endsWith('.js')) continue
        fs.copyFileSync(path.join(source, entry), path.join(target, entry))
        copied++
      }
      this.info(`pdfjs wasm: 已拷入 ${copied} 个文件 -> dist/pdfjs/wasm`)
    },
  }
}

export default defineConfig({
  // 由后端单进程托管时用 VITE_APP_BASE=/app/ 打包；默认 '/' 保持原开发/部署行为不变
  base: APP_BASE,
  plugins: [vue(), pdfjsWasm()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    host: '0.0.0.0',
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/v1/proxy': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
