'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { fetchProjects, type Project, type SearchMode } from '@/lib/api'
import { useSSE } from '@/hooks/useSSE'
import { ErrorBoundary } from '@/components/ErrorBoundary'

interface Source { project: string; file: string; role: string; score: number }
interface HistoryItem {
  query: string; mode: SearchMode; answer: string
  sources: Source[]; timestamp: number
}

type SearchEvent =
  | { type: 'sources'; chunks: Source[] }
  | { type: 'token'; text: string }
  | { type: 'done'; total_tokens?: number }
  | { type: 'error'; message: string; request_id?: string }

const BASE = process.env.NEXT_PUBLIC_API_URL ?? '/api'

export default function SearchPage() {
  return (
    <ErrorBoundary>
      <SearchContent />
    </ErrorBoundary>
  )
}

function SearchContent() {
  const [query, setQuery]         = useState('')
  const [mode, setMode]           = useState<SearchMode>('answer')
  const [project, setProject]     = useState('')
  const [projects, setProjects]   = useState<Project[]>([])
  const [answer, setAnswer]       = useState('')
  const [sources, setSources]     = useState<Source[]>([])
  const [errorMsg, setErrorMsg]   = useState<string | null>(null)
  const [thread, setThread]       = useState<{role: string; content: string}[]>([])
  const [isFollowUp, setIsFollowUp] = useState(false)
  const [history, setHistory]     = useState<HistoryItem[]>([])
  const [showHistory, setShow]    = useState(false)
  const answerRef = useRef<HTMLDivElement>(null)
  const answerAccum = useRef('')

  useEffect(() => { fetchProjects().then(setProjects).catch(() => {}) }, [])

  const { status, start, cancel, requestId } = useSSE<SearchEvent>({
    onEvent(event) {
      if (event.type === 'sources') {
        setSources(event.chunks)
      } else if (event.type === 'token') {
        answerAccum.current += event.text
        setAnswer(answerAccum.current)
        answerRef.current?.scrollTo({ top: answerRef.current.scrollHeight })
      }
    },
    onDone() {
      const fullAnswer = answerAccum.current
      // Сохраняем в историю сессии
      setHistory(prev => [{
        query, mode, answer: fullAnswer,
        sources, timestamp: Date.now(),
      }, ...prev.slice(0, 49)])
      // Сохраняем в тред для многоходового диалога
      if (mode === 'answer') {
        setThread(prev => [
          ...prev,
          { role: 'user',      content: query },
          { role: 'assistant', content: fullAnswer },
        ])
        setIsFollowUp(true)
      }
    },
    onError(message, rid) {
      setErrorMsg(`${message}${rid ? ` (id: ${rid.slice(0, 8)})` : ''}`)
    },
  })

  const isLoading = status === 'streaming'

  const handleSearch = useCallback(() => {
    if (!query.trim() || isLoading) return
    setAnswer(''); setErrorMsg(null); setSources([])
    answerAccum.current = ''

    const endpoint = mode === 'global' ? 'global'
      : mode === 'patch' ? 'patch'
      : mode === 'answer' ? 'answer'
      : ''

    if (!endpoint) return

    // При follow-up вопросе передаём историю треда
    const historyToSend = (mode === 'answer' && isFollowUp && thread.length > 0)
      ? thread.slice(-6)  // последние 3 хода
      : []

    start(() => fetch(`${BASE}/search/${endpoint}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        query: query.trim(),
        project: project || null,
        top_k: 5,
        mode,
        history: historyToSend,
      }),
    }))
  }, [query, mode, project, isLoading, start])

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      handleSearch()
    } else if (e.key === 'Escape') {
      if (isLoading) {
        cancel()
      } else if (answer || sources.length > 0) {
        // Первый Escape — сбрасываем результаты
        setAnswer(''); setSources([]); setErrorMsg(null)
      } else {
        // Второй Escape — очищаем поле
        setQuery('')
      }
    }
  }

  return (
    <div style={{ maxWidth: 860, margin: '0 auto', display: 'flex', flexDirection: 'column', gap: 16 }}>

      {/* Поле поиска */}
      <div style={{
        display: 'flex', gap: 8, background: 'var(--color-surface)',
        border: '1px solid var(--color-border)', borderRadius: 10, padding: '10px 12px',
      }}>
        <textarea
          value={query} onChange={e => setQuery(e.target.value)} onKeyDown={handleKeyDown}
          placeholder="Поиск... (⌘Enter отправить · Esc отменить)"
          rows={2}
          style={{
            flex: 1, resize: 'none', border: 'none', outline: 'none',
            background: 'transparent', color: 'var(--color-text)',
            fontSize: 14, lineHeight: 1.5, fontFamily: 'inherit',
          }}
        />
        <button
          onClick={isLoading ? cancel : handleSearch}
          disabled={!isLoading && !query.trim()}
          style={{
            padding: '7px 16px', background: isLoading ? '#d85a30' : 'var(--color-accent)',
            color: '#fff', border: 'none', borderRadius: 7, cursor: 'pointer', fontSize: 13, flexShrink: 0,
          }}
        >
          {isLoading ? '⏹ Стоп' : 'Искать'}
        </button>
      </div>

      {/* Режим + проект */}
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        {(['answer', 'search', 'patch', 'global'] as SearchMode[]).map(m => (
          <button key={m} onClick={() => setMode(m)} style={{
            padding: '5px 12px', borderRadius: 6, border: '1px solid var(--color-border)',
            background: mode === m ? 'var(--color-accent-light)' : 'transparent',
            color: mode === m ? 'var(--color-accent)' : 'var(--color-text-muted)',
            fontSize: 12, cursor: 'pointer', fontWeight: mode === m ? 500 : 400,
          }}>
            {m === 'answer' ? '💬 Ответ' : m === 'search' ? '🔍 Поиск' : m === 'patch' ? '🔧 Патч' : '🌐 GlobalRAG'}
          </button>
        ))}

        <div style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
          <select value={project} onChange={e => setProject(e.target.value)} style={selectStyle}>
            <option value="">Все проекты</option>
            {projects.map(p => <option key={p.name} value={p.name}>{p.name}</option>)}
          </select>
          {history.length > 0 && (
            <button onClick={() => setShow(!showHistory)} style={ghostBtnStyle}>
              ⏱ ({history.length})
            </button>
          )}
        </div>
      </div>

      {/* Ошибка */}
      {errorMsg && (
        <div style={{
          padding: '10px 14px', borderRadius: 8,
          background: 'rgba(210,90,48,0.08)', border: '1px solid rgba(210,90,48,0.25)',
          fontSize: 13, color: 'var(--color-error)',
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        }}>
          <span>❌ {errorMsg}</span>
          <button onClick={() => setErrorMsg(null)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'inherit', fontSize: 16 }}>×</button>
        </div>
      )}

      {/* История */}
      {showHistory && (
        <div style={{ border: '1px solid var(--color-border)', borderRadius: 10, overflow: 'hidden', maxHeight: 260, overflowY: 'auto' }}>
          {history.map((item, i) => (
            <button key={i} onClick={() => {
              setQuery(item.query); setMode(item.mode)
              setAnswer(item.answer); setSources(item.sources); setShow(false)
            }} style={{
              display: 'block', width: '100%', textAlign: 'left',
              padding: '10px 14px', borderBottom: i < history.length - 1 ? '1px solid var(--color-border)' : 'none',
              background: 'transparent', border: 'none', cursor: 'pointer', color: 'var(--color-text)',
            }}>
              <div style={{ fontSize: 13, fontWeight: 500, marginBottom: 2 }}>{item.query}</div>
              <div style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>
                {item.mode} · {new Date(item.timestamp).toLocaleTimeString()}
              </div>
            </button>
          ))}
        </div>
      )}

      {/* Источники */}
      {sources.length > 0 && (
        <div style={{ border: '1px solid var(--color-border)', borderRadius: 10, overflow: 'hidden' }}>
          <div style={{ padding: '8px 14px', fontSize: 12, fontWeight: 500, color: 'var(--color-text-muted)', borderBottom: '1px solid var(--color-border)', background: 'var(--color-surface)' }}>
            Источники ({sources.length})
          </div>
          {sources.map((src, i) => (
            <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '7px 14px', borderBottom: i < sources.length - 1 ? '1px solid var(--color-border)' : 'none' }}>
              <span style={{ padding: '1px 6px', borderRadius: 4, fontSize: 10, fontWeight: 500, background: 'var(--color-accent-light)', color: 'var(--color-accent)', flexShrink: 0 }}>{src.score}</span>
              <span style={{ fontSize: 11, color: 'var(--color-text-muted)', flexShrink: 0 }}>{src.project}</span>
              <span style={{ fontSize: 12, fontFamily: 'monospace', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{src.file}</span>
              <span style={{ fontSize: 11, color: 'var(--color-text-muted)', flexShrink: 0, marginLeft: 'auto' }}>{src.role}</span>
              <button
                onClick={() => navigator.clipboard.writeText(src.file)}
                title="Копировать путь к файлу"
                style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--color-text-muted)', fontSize: 12, flexShrink: 0, padding: '0 2px' }}
              >📋</button>
            </div>
          ))}
        </div>
      )}

      {/* Ответ */}
      {(answer || isLoading) && (
        <div style={{ border: '1px solid var(--color-border)', borderRadius: 10, overflow: 'hidden' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 14px', borderBottom: '1px solid var(--color-border)', background: 'var(--color-surface)' }}>
            <span style={{ fontSize: 12, fontWeight: 500, color: 'var(--color-text-muted)', display: 'flex', alignItems: 'center', gap: 6 }}>
              {isLoading && <span style={{ width: 7, height: 7, borderRadius: '50%', background: 'var(--color-accent)', display: 'inline-block', animation: 'pulse 1s infinite' }} />}
              {isLoading ? 'Генерирую...' : `Ответ${isFollowUp && thread.length > 0 ? ` · 💬 ${Math.floor(thread.length / 2)} ходов` : ''}${requestId ? ` · id:${requestId.slice(0, 6)}` : ''}`}
            </span>
            {answer && !isLoading && (
              <button onClick={() => navigator.clipboard.writeText(answer)} style={ghostBtnStyle}>📋 Копировать</button>
            )}
          </div>
          <div ref={answerRef} style={{ padding: 16, fontSize: 13, lineHeight: 1.7, whiteSpace: 'pre-wrap', maxHeight: 500, overflowY: 'auto' }}>
            {answer}{isLoading && <span style={{ opacity: 0.4 }}>▌</span>}
          </div>
        </div>
      )}

      {/* Пустое состояние */}
      {!answer && !isLoading && sources.length === 0 && !errorMsg && (
        <div style={{ textAlign: 'center', padding: '40px 0', color: 'var(--color-text-muted)', fontSize: 13 }}>
          <div style={{ fontSize: 36, marginBottom: 12 }}>🔍</div>
          <div style={{ marginBottom: 6 }}>Задай вопрос по своим проектам</div>
          <div style={{ fontSize: 12, opacity: 0.7 }}>«где обрабатываются ошибки?» · «как устроена авторизация?»</div>
          <div style={{ fontSize: 11, opacity: 0.5, marginTop: 4 }}>После первого ответа можно задавать уточняющие вопросы — история сохраняется</div>
        </div>
      )}

      <style>{`@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.3} }`}</style>
    </div>
  )
}

const selectStyle: React.CSSProperties = {
  padding: '5px 10px', borderRadius: 6, border: '1px solid var(--color-border)',
  background: 'var(--color-surface)', color: 'var(--color-text)', fontSize: 12, cursor: 'pointer',
}
const ghostBtnStyle: React.CSSProperties = {
  padding: '5px 12px', borderRadius: 6, border: '1px solid var(--color-border)',
  background: 'transparent', color: 'var(--color-text-muted)', fontSize: 12, cursor: 'pointer',
}
