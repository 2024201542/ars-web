import mermaid from 'mermaid'

let ready = false

function ensureMermaid() {
  if (ready) return
  mermaid.initialize({
    startOnLoad: false,
    securityLevel: 'strict',
    theme: 'neutral',
    fontFamily: 'Source Han Sans SC, Noto Sans SC, Microsoft YaHei, sans-serif',
  })
  ready = true
}

export async function renderMermaidBlocks(root: ParentNode | null | undefined) {
  if (!root) return
  const nodes = Array.from(root.querySelectorAll('code.language-mermaid'))
  if (!nodes.length) return
  ensureMermaid()
  let index = 0
  for (const code of nodes) {
    if (code.getAttribute('data-drawing') === '1') continue
    code.setAttribute('data-drawing', '1')
    const text = (code.textContent || '').trim()
    const pre = code.parentElement?.tagName === 'PRE' ? code.parentElement : code
    const host = document.createElement('div')
    host.className = 'ars-mermaid overflow-x-auto'
    if (!text) {
      pre.replaceWith(host)
      continue
    }
    try {
      const drawn = await mermaid.render(`ars-mmd-${Date.now()}-${index}`, text)
      index += 1
      host.innerHTML = drawn.svg
    } catch {
      host.textContent = '这张结构图没有画出来'
    }
    pre.replaceWith(host)
  }
}
