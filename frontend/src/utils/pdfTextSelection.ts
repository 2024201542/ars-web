/** 让 PDF 文字层的高亮停在真正选中的字上，避免拖到空白处时跳到别的段落。 */

const layers = new Map<HTMLElement, HTMLElement>()
let prevRange: Range | null = null
let isPointerDown = false
let listening = false
let handling = false

function reset(end: HTMLElement, textLayer: HTMLElement) {
  textLayer.append(end)
  end.style.width = ''
  end.style.height = ''
  end.style.userSelect = ''
  textLayer.classList.remove('selecting')
}

function onSelectionChange() {
  if (handling) return
  handling = true
  try {
    adjustSelection()
  } finally {
    handling = false
  }
}

function adjustSelection() {
  const selection = document.getSelection()
  if (!selection || selection.rangeCount === 0) {
    layers.forEach(reset)
    prevRange = null
    return
  }
  const active = new Set<HTMLElement>()
  for (let i = 0; i < selection.rangeCount; i++) {
    const range = selection.getRangeAt(i)
    for (const textLayer of layers.keys()) {
      if (active.has(textLayer)) continue
      try {
        if (range.intersectsNode(textLayer)) active.add(textLayer)
      } catch {
        /* 文字层已经卸掉 */
      }
    }
  }
  for (const [textLayer, end] of layers) {
    if (active.has(textLayer)) textLayer.classList.add('selecting')
    else reset(end, textLayer)
  }

  const range = selection.getRangeAt(0)
  const modifyStart = !!prevRange && (
    range.compareBoundaryPoints(Range.END_TO_END, prevRange) === 0
    || range.compareBoundaryPoints(Range.START_TO_END, prevRange) === 0
  )
  let anchor: Node | null = modifyStart ? range.startContainer : range.endContainer
  if (anchor?.nodeType === Node.TEXT_NODE) anchor = anchor.parentNode
  const anchorEl = anchor as HTMLElement | null
  if (!anchorEl || anchorEl.classList?.contains('endOfContent')) {
    prevRange = range.cloneRange()
    return
  }
  if (!modifyStart && range.endOffset === 0) {
    let node: Node | null = anchorEl
    do {
      while (node && !node.previousSibling) node = node.parentNode
      node = node?.previousSibling ?? null
    } while (node && !node.childNodes.length)
    if (node) anchor = node
  }
  const placed = anchor as HTMLElement
  const textLayer = placed.parentElement?.closest('.textLayer') as HTMLElement | null
  const end = textLayer ? layers.get(textLayer) : undefined
  if (end && textLayer && placed.parentElement) {
    end.style.width = textLayer.style.width
    end.style.height = textLayer.style.height
    end.style.userSelect = 'text'
    placed.parentElement.insertBefore(end, modifyStart ? placed : placed.nextSibling)
  }
  prevRange = range.cloneRange()
}

function onPointerDown() {
  isPointerDown = true
}

function onPointerUp() {
  isPointerDown = false
  layers.forEach(reset)
}

function onKeyUp() {
  if (!isPointerDown) layers.forEach(reset)
}

function listen() {
  if (listening) return
  listening = true
  document.addEventListener('selectionchange', onSelectionChange)
  document.addEventListener('pointerdown', onPointerDown)
  document.addEventListener('pointerup', onPointerUp)
  document.addEventListener('keyup', onKeyUp)
  window.addEventListener('blur', onPointerUp)
}

export function attachPdfTextLayer(textLayer: HTMLElement) {
  listen()
  let end = textLayer.querySelector(':scope > .endOfContent') as HTMLElement | null
  if (!end) {
    end = document.createElement('div')
    end.className = 'endOfContent'
    textLayer.append(end)
  }
  layers.set(textLayer, end)
}

export function detachPdfTextLayers(root?: ParentNode | null) {
  const drop = root
    ? [...layers.keys()].filter(layer => root.contains(layer) || layer === root)
    : [...layers.keys()]
  for (const layer of drop) {
    const end = layers.get(layer)
    layers.delete(layer)
    if (end) reset(end, layer)
  }
  if (layers.size === 0) prevRange = null
}
