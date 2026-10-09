/** SSE 流式消息处理 */
import { ref, computed } from 'vue'
import { api } from '@/api'
import type { DebatePayload, DebateVoice } from '@/types'
import { useSessionStore } from '@/stores/session'
import { toast } from '@/composables/useToast'

export function useChatStream(getSessionId: () => string, emitDone: () => void) {
  const sessionStore = useSessionStore()
  
  const isStreaming = ref(false)
  const resultContent = ref('')
  const progressTokens = ref(0)
  const progressPhase = ref('')
  const lastToolUse = ref('')
  // 辩论/辩题的实时流：模型正在写的那一段（逐字追加），结束后清空
  const liveStream = ref<{ key: string; kind: string; name: string; round: number; thinking: string; answer: string } | null>(null)

  const statusText = computed(() => {
    if (lastToolUse.value) return `正在使用工具：${lastToolUse.value}`
    if (progressTokens.value > 0) return '正在写回答…'
    if (progressPhase.value === 'init') return '正在启动…'
    return '正在连接模型…'
  })

  function _parseLine(line: string, p: { evt: string; dat: string }, f: (d: any) => void) {
    const t = line.trimEnd()
    if (!t || t === ': heartbeat') { if (p.evt) { try { f(JSON.parse(p.dat)) } catch {} p.evt=''; p.dat='' } return }
    if (t.startsWith(':') && t !== ': heartbeat') return
    if (t.startsWith('event: ')) { if (p.evt) try { f(JSON.parse(p.dat)) } catch {} p.evt = t.slice(7).trim(); p.dat = ''; return }
    if (t.startsWith('data: ')) { p.dat += (p.dat ? '\n' : '') + t.slice(6) }
  }

  function lastAssistant() {
    const ms = sessionStore.messages
    const l = ms[ms.length - 1]
    return l && l.role === 'assistant' ? l : null
  }

  async function sendMessage(msg: string, modelToUse?: string, openPath?: string, pipelineAction?: string, debateModels?: string[], debate?: DebatePayload) {
    if (isStreaming.value) return
    isStreaming.value = true; resultContent.value = ''
    progressTokens.value = 0; progressPhase.value = ''; lastToolUse.value = ''

    // 消息气泡由 ChatPanel.doSend 预先插入；此处只负责流式写入，避免重复一对问答
    if (!lastAssistant()) {
      sessionStore.addMessage({
        id: Date.now() + 1,
        session_id: getSessionId(),
        role: 'assistant',
        content: '',
        agent_name: null,
        phase_name: null,
        metadata: null,
        created_at: new Date().toISOString(),
      })
    }

    let last = Date.now()
    try {
      const r = await api.chatSSE(getSessionId(), msg, modelToUse, openPath, pipelineAction, debateModels, debate)
      if (!r.ok) {
        const e = await r.json().catch(()=>({detail:`${r.status}`}))
        // FastAPI 校验失败时 detail 是对象数组，直接拼接会变成 [object Object]
        const detail = Array.isArray(e.detail)
          ? e.detail.map((x: any) => {
              const where = Array.isArray(x?.loc) ? x.loc.filter((p: any) => p !== 'body').join('.') : ''
              return where ? `${where}: ${x?.msg || ''}` : (x?.msg || JSON.stringify(x))
            }).join('；')
          : (e.detail || '请求失败')
        throw new Error(detail)
      }
      if (!r.body) throw new Error('无响应流')
      const rd = r.body.getReader(); const dc = new TextDecoder()
      let buf = ''; const pen = { evt: '', dat: '' }
      function fl(d: any) { last = Date.now()
        const l = lastAssistant()
        if (pen.evt === 'message' && d.delta) {
          resultContent.value += d.delta
          if (l) { l._streaming = true; l._rawContent = resultContent.value; l.content = resultContent.value }
        }
        else if (pen.evt === 'progress') { progressTokens.value = d.tokens||0; progressPhase.value = d.phase||'' }
        else if (pen.evt === 'phase_start' && d.phase === 'tool') { lastToolUse.value = d.description||'' }
        else if (pen.evt === 'files_changed' && l) { l.edits = d }
        else if (pen.evt === 'pipeline' && l) { l.pipeline = d }
        else if (pen.evt === 'debate_topic' && l) { l.debatePlan = d }
        else if (pen.evt === 'literature' && l) { l.literature = d }
        else if (pen.evt === 'debate_pause' && l) { l.debateHold = d }
        else if (pen.evt === 'debate_stream') {
          // 这一位开始/结束写了；开始就先把空卡片挂出来，好让用户看到逐字增长
          if (d?.stage === 'start') {
            liveStream.value = {
              key: String(d.kind || 'speech') + '-' + String(d.model || d.name || '') + '-' + String(d.round || 1),
              kind: String(d.kind || 'speech'),
              name: String(d.name || ''),
              round: Number(d.round || 1),
              thinking: '',
              answer: '',
            }
          } else if (d?.stage === 'end') {
            // 完整卡片由随后的 debate_voice 事件覆盖，这里先留住内容避免闪烁
          }
        }
        else if (pen.evt === 'debate_delta') {
          const part = String(d?.part || 'answer')
          if (!liveStream.value) {
            liveStream.value = {
              key: String(d?.kind || 'speech') + '-' + String(d?.model || '') + '-' + String(d?.round || 1),
              kind: String(d?.kind || 'speech'),
              name: '',
              round: Number(d?.round || 1),
              thinking: '',
              answer: '',
            }
          }
          const cur = liveStream.value
          if (part === 'thinking') cur.thinking += String(d?.delta || '')
          else cur.answer += String(d?.delta || '')
        }
        else if (pen.evt === 'debate_voice' && l) {
          l.debateHold = null
          liveStream.value = null
          const voices: DebateVoice[] = [...(l.debate?.voices || [])]
          const incoming = d as DebateVoice
          if (incoming.kind === 'summary' || incoming.kind === 'judge') voices.push(incoming)
          else {
            const idx = voices.findIndex((item) => item.model === incoming.model && item.round === incoming.round && item.kind !== 'summary' && item.kind !== 'judge')
            if (idx >= 0) voices[idx] = incoming
            else voices.push(incoming)
          }
          l.debate = { voices }
        }
        else if (pen.evt === 'done') {
          if (l) { l._streaming = false; l.debateHold = null; l.content = l._rawContent || l.content }
          emitDone()
        }
        else if (pen.evt === 'error') {
          const raw = d?.message || d?.code || '未知错误'
          const errText = /401|403|invalid api key|authentication/i.test(raw)
            ? 'DeepSeek 拒绝了当前密钥，所以回答停在这里。请点左下角的模型名，到设置里重新保存 API Key，然后再发一次。'
            : /UnicodeDecodeError|codec can't decode/i.test(raw)
              ? '模型已经回复，但读取时编码出错，内容没有显示出来。请再发一次。'
              : raw
          resultContent.value = resultContent.value.trim() ? `${resultContent.value}\n\n${errText}` : errText
          if (l) {
            l._streaming = false
            l.content = errText
            if (l.pipeline) l.pipeline = { ...l.pipeline, awaiting: false }
          }
        }
      }
      try { while (true) { const { done, value } = await rd.read()
        if (done) { buf+=dc.decode(); buf.split('\n').forEach((l: string)=>_parseLine(l,pen,fl)); if (pen.evt) { try { fl(JSON.parse(pen.dat||'{}')) } catch {} } break }
        buf+=dc.decode(value,{stream:true}); const ls=buf.split('\n'); buf=ls.pop()||''; ls.forEach((l: string)=>{ if (l.trim()===': heartbeat') last=Date.now(); _parseLine(l,pen,fl) })
        if (Date.now()-last>30000){toast.warning('连接可能已中断…'); last=Date.now()} }
      } finally { try { rd.releaseLock() } catch {} }
    } catch (e: any) {
      if (e.name !== 'AbortError') {
        resultContent.value += `\n\n> **⚠️ ${e.message||'未知错误'}**\n`
        const l = lastAssistant()
        if (l) { l._streaming = false; l.content = resultContent.value }
      }
    }
    finally { isStreaming.value = false; emitDone() }
  }

  return { isStreaming, resultContent, progressTokens, progressPhase, lastToolUse, statusText, liveStream, sendMessage, abort: ()=> { isStreaming.value = false } }
}
