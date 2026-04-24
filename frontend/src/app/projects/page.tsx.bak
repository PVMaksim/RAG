'use client'

import { useCallback, useState } from 'react'
import { estimateGraphCost, makeGitCloneFetcher, makeUploadFetcher, type Project } from '@/lib/api'

const BASE = typeof process !== 'undefined' ? (process.env.NEXT_PUBLIC_API_URL ?? '/api') : '/api'
import { useSSE } from '@/hooks/useSSE'
import { useProjects } from '@/hooks/useProjects'
import { ErrorBoundary } from '@/components/ErrorBoundary'

const BASE = process.env.NEXT_PUBLIC_API_URL ?? '/api'

// ── Типы событий ──────────────────────────────────────────────────────────────

type ScanEvent =
  | { type: 'start';    project: string; files_total: number }
  | { type: 'progress'; files_scanned: number; files_indexed: number; files_total: number; current_file: string }
  | { type: 'done';     files_indexed: number; duration_sec: number }
  | { type: 'error';    message: string }

type GraphEvent =
  | { type: 'start';    project: string; total_files: number }
  | { type: 'progress'; phase: string; processed?: number; total?: number; current_file?: string }
  | { type: 'done';     nodes: number; edges: number; communities: number }
  | { type: 'error';    message: string }

// ── Страница ──────────────────────────────────────────────────────────────────

export default function ProjectsPage() {
  return (
    <ErrorBoundary>
      <ProjectsContent />
    </ErrorBoundary>
  )
}

function ProjectsContent() {
  const { projects, loading, error: loadError, reload, remove, estimates, getEstimate } = useProjects()

  const [addPath, setAddPath]           = useState('')
  const [showAdd, setShowAdd]           = useState(false)
  const [addMode, setAddMode]           = useState<'path' | 'git' | 'zip'>('path')
  const [gitUrl, setGitUrl]             = useState('')
  const [gitName, setGitName]           = useState('')
  const [gitError, setGitError]         = useState<string | null>(null)
  const [zipFile, setZipFile]           = useState<File | null>(null)
  const [dragOver, setDragOver]         = useState(false)
  const [scanTarget, setScanTarget]     = useState<string | null>(null)
  const [scanResult, setScanResult]     = useState<{ indexed: number; duration: number } | null>(null)
  const [scanError, setScanError]       = useState<string | null>(null)
  const [graphTarget, setGraphTarget]   = useState<string | null>(null)
  const [graphResult, setGraphResult]   = useState<{ nodes: number; edges: number; communities: number } | null>(null)
  const [graphError, setGraphError]     = useState<string | null>(null)
  const [scanProgress, setScanProgress] = useState(0)
  const [scanFile, setScanFile]         = useState('')
  const [graphPhase, setGraphPhase]     = useState('')
  const [graphProgress, setGraphProgress] = useState(0)

  // ── SSE: git clone ──────────────────────────────────────────────────────────
  const { status: gitStatus, start: startGit, cancel: cancelGit } = useSSE<ScanEvent>({
    onEvent(ev) {
      if (ev.type === 'progress') {
        setScanProgress(Math.round(((ev.files_scanned ?? 0) / Math.max(ev.files_total ?? 1, 1)) * 100))
        setScanFile(ev.current_file ?? '')
      }
    },
    onDone() { setScanTarget(null); reload() },
    onError(msg) { setScanTarget(null); setGitError(msg) },
  })

  // ── SSE: сканирование ───────────────────────────────────────────────────────
  const { status: scanStatus, start: startScan, cancel: cancelScan } = useSSE<ScanEvent>({
    onEvent(ev) {
      if (ev.type === 'progress') {
        const pct = ev.files_total > 0
          ? Math.round((ev.files_scanned / ev.files_total) * 100)
          : 0
        setScanProgress(pct)
        setScanFile(ev.current_file)
      }
    },
    onDone() {
      setScanTarget(null)
      reload()
    },
    onError(msg) {
      setScanTarget(null)
      setScanError(msg)
    },
  })

  // ── SSE: построение графа ───────────────────────────────────────────────────
  const { status: graphStatus, start: startGraph, cancel: cancelGraph } = useSSE<GraphEvent>({
    onEvent(ev) {
      if (ev.type === 'progress') {
        setGraphPhase(ev.phase ?? '')
        if (ev.processed && ev.total) {
          setGraphProgress(Math.round((ev.processed / ev.total) * 100))
        }
      } else if (ev.type === 'done') {
        setGraphResult({ nodes: ev.nodes, edges: ev.edges, communities: ev.communities })
      }
    },
    onDone() {
      setGraphTarget(null)
      reload()
    },
    onError(msg) {
      setGraphTarget(null)
      setGraphError(msg)
    },
  })

  // ── Handlers ────────────────────────────────────────────────────────────────

  const handleScan = useCallback((path: string, name: string) => {
    setScanTarget(name)
    setScanResult(null)
    setScanError(null)
    setScanProgress(0)
    setScanFile('')
    startScan(() => fetch(`${BASE}/projects/${name}/scan-path`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path }),
    }))
  }, [startScan])

  const handleGitClone = useCallback(() => {
    const url = gitUrl.trim()
    if (!url) return
    const name = gitName.trim() || url.split('/').pop()?.replace('.git', '') || 'project'
    setGitError(null)
    setScanTarget(name)
    setScanProgress(0)
    setScanFile('')
    setShowAdd(false)
    startGit(() => fetch(`${BASE}/projects/git/clone`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ git_url: url, project_name: gitName.trim() || undefined }),
    }))
  }, [gitUrl, gitName, startGit])

  const handleZipUpload = useCallback(() => {
    if (!zipFile) return
    const name = gitName.trim() || zipFile.name.replace(/\.zip$/i, '')
    setGitError(null)
    setScanTarget(name)
    setScanProgress(0)
    setScanFile('')
    setShowAdd(false)
    startGit(makeUploadFetcher(zipFile, gitName.trim() || undefined))
  }, [zipFile, gitName, startGit])

  const handleBuildGraph = useCallback((name: string) => {
    setGraphTarget(name)
    setGraphResult(null)
    setGraphError(null)
    setGraphProgress(0)
    setGraphPhase('entity_extraction')
    startGraph(() => fetch(`${BASE}/projects/${name}/graph/build`, { method: 'POST' }))
  }, [startGraph])

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    setDragOver(false)
    const file = e.dataTransfer.files[0] as File & { path?: string }
    const path = file?.path ?? ''
    if (path) { setAddPath(path); setShowAdd(true) }
  }

  const handleAdd = () => {
    if (!addPath.trim()) return
    const name = addPath.trim().split('/').pop() ?? addPath
    handleScan(addPath.trim(), name)
    setShowAdd(false)
    setAddPath('')
  }

  const isScanningAny = scanStatus === 'streaming' || gitStatus === 'streaming'
  const isBuildingAny = graphStatus === 'streaming'

  return (
    <div style={{ maxWidth: 760, margin: '0 auto', display: 'flex', flexDirection: 'column', gap: 16 }}>

      {/* Заголовок */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <h1 style={{ fontSize: 18, fontWeight: 500 }}>Проекты</h1>
        <button onClick={() => setShowAdd(!showAdd)} style={primaryBtn}>+ Добавить</button>
      </div>

      {/* Ошибки загрузки */}
      {(loadError || scanError || graphError) && (
        <div style={errorBox}>
          ❌ {loadError ?? scanError ?? graphError}
          <button onClick={() => { setScanError(null); setGraphError(null) }}
            style={{ background: 'none', border: 'none', cursor: 'pointer', marginLeft: 8 }}>×</button>
        </div>
      )}

      {/* Форма добавления */}
      {showAdd && (
        <div style={{ padding: 14, background: 'var(--color-surface)', border: '1px solid var(--color-border)', borderRadius: 10, display: 'flex', flexDirection: 'column', gap: 10 }}>
          {/* Переключатель режима */}
          <div style={{ display: 'flex', gap: 6 }}>
            {(['path', 'git', 'zip'] as const).map(m => (
              <button key={m} onClick={() => setAddMode(m)} style={{
                padding: '4px 12px', borderRadius: 6, fontSize: 12,
                border: '1px solid var(--color-border)', cursor: 'pointer',
                background: addMode === m ? 'var(--color-accent-light)' : 'transparent',
                color: addMode === m ? 'var(--color-accent)' : 'var(--color-text-muted)',
                fontWeight: addMode === m ? 500 : 400,
              }}>
                {m === 'path' ? '📁 Путь' : m === 'git' ? '🔗 Git URL' : '📦 ZIP'}
              </button>
            ))}
          </div>

          {addMode === 'path' ? (
            <div style={{ display: 'flex', gap: 8 }}>
              <input value={addPath} onChange={e => setAddPath(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && handleAdd()}
                placeholder="/путь/к/проекту" autoFocus style={inputStyle} />
              <button onClick={handleAdd} disabled={!addPath.trim()} style={primaryBtn}>Сканировать</button>
            </div>
          ) : addMode === 'zip' ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <label style={{
                display: 'flex', alignItems: 'center', gap: 10,
                padding: '10px 14px', border: '2px dashed var(--color-border)',
                borderRadius: 8, cursor: 'pointer',
                background: zipFile ? 'var(--color-accent-light)' : 'transparent',
              }}>
                <input type="file" accept=".zip" style={{ display: 'none' }}
                  onChange={e => setZipFile(e.target.files?.[0] ?? null)} />
                <span style={{ fontSize: 20 }}>📦</span>
                <span style={{ fontSize: 13, color: 'var(--color-text-muted)' }}>
                  {zipFile ? zipFile.name : 'Выбери ZIP архив проекта'}
                </span>
              </label>
              <div style={{ display: 'flex', gap: 8 }}>
                <input value={gitName} onChange={e => setGitName(e.target.value)}
                  placeholder="Имя проекта (необязательно)" style={{ ...inputStyle, flex: 1 }} />
                <button onClick={handleZipUpload} disabled={!zipFile} style={primaryBtn}>
                  Загрузить
                </button>
              </div>
              <div style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>
                Максимум 100MB · Только .zip файлы
              </div>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <input value={gitUrl} onChange={e => setGitUrl(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && handleGitClone()}
                placeholder="https://github.com/user/project.git" autoFocus style={inputStyle} />
              <div style={{ display: 'flex', gap: 8 }}>
                <input value={gitName} onChange={e => setGitName(e.target.value)}
                  placeholder="Имя проекта (необязательно)" style={{ ...inputStyle, flex: 1 }} />
                <button onClick={handleGitClone} disabled={!gitUrl.trim()} style={primaryBtn}>
                  Клонировать
                </button>
              </div>
              {gitError && (
                <div style={{ fontSize: 12, color: 'var(--color-error, #a32d2d)', padding: '6px 10px',
                  background: 'rgba(163,45,45,0.08)', borderRadius: 6 }}>
                  ❌ {gitError}
                </div>
              )}
              <div style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>
                Поддерживаются: https://github.com/... · git@github.com:...
              </div>
            </div>
          )}
        </div>
      )}

      {/* Список проектов */}
      {loading ? (
        <div style={{ padding: '32px', textAlign: 'center', color: 'var(--color-text-muted)', fontSize: 13 }}>Загружаю...</div>
      ) : projects.length > 0 ? (
        <div style={{ border: '1px solid var(--color-border)', borderRadius: 10, overflow: 'hidden' }}>
          {projects.map((p, i) => (
            <ProjectRow
              key={p.name}
              project={p}
              isLast={i === projects.length - 1}
              isScanningThis={scanTarget === p.name}
              isBuildingThis={graphTarget === p.name}
              isAnyBusy={isScanningAny || isBuildingAny}
              scanProgress={scanTarget === p.name ? scanProgress : 0}
              scanFile={scanTarget === p.name ? scanFile : ''}
              graphPhase={graphTarget === p.name ? graphPhase : ''}
              graphProgress={graphTarget === p.name ? graphProgress : 0}
              graphResult={graphTarget !== p.name && graphResult?.nodes ? null : graphResult}
              estimate={estimates[p.name]}
              onScan={() => handleScan(p.name, p.name)}
              onCancelScan={cancelScan}
              onDelete={() => remove(p.name).catch(() => {})}
              onEstimate={() => getEstimate(p.name)}
              onBuildGraph={() => handleBuildGraph(p.name)}
              onCancelGraph={cancelGraph}
            />
          ))}
        </div>
      ) : (
        <div style={{ padding: '24px', textAlign: 'center', color: 'var(--color-text-muted)', fontSize: 13, border: '1px solid var(--color-border)', borderRadius: 10 }}>
          Нет проиндексированных проектов. Добавь проект выше.
        </div>
      )}

      {/* Drag & Drop зона */}
      <div
        onDrop={handleDrop}
        onDragOver={e => { e.preventDefault(); setDragOver(true) }}
        onDragLeave={() => setDragOver(false)}
        style={{
          border: `2px dashed ${dragOver ? 'var(--color-accent)' : 'var(--color-border)'}`,
          borderRadius: 10,
          padding: '28px 20px',
          textAlign: 'center',
          color: dragOver ? 'var(--color-accent)' : 'var(--color-text-muted)',
          fontSize: 13,
          background: dragOver ? 'var(--color-accent-light)' : 'transparent',
          transition: 'all 0.15s',
        }}
      >
        <div style={{ fontSize: 28, marginBottom: 8 }}>📁</div>
        <div>Перетащи папку проекта сюда</div>
        <div style={{ fontSize: 12, marginTop: 4, opacity: 0.7 }}>или нажми «+ Добавить» и укажи путь</div>
      </div>
    </div>
  )
}

// ── ProjectRow ────────────────────────────────────────────────────────────────

function ProjectRow({
  project, isLast, isScanningThis, isBuildingThis, isAnyBusy,
  scanProgress, scanFile, graphPhase, graphProgress, graphResult,
  estimate, onScan, onCancelScan, onDelete, onEstimate, onBuildGraph, onCancelGraph,
}: {
  project: Project; isLast: boolean
  isScanningThis: boolean; isBuildingThis: boolean; isAnyBusy: boolean
  scanProgress: number; scanFile: string
  graphPhase: string; graphProgress: number
  graphResult: { nodes: number; edges: number; communities: number } | null
  estimate?: { estimated_tokens: number; estimated_cost_display: string }
  onScan: () => void; onCancelScan: () => void; onDelete: () => void
  onEstimate: () => void; onBuildGraph: () => void; onCancelGraph: () => void
}) {
  return (
    <div style={{
      padding: '14px 16px',
      borderBottom: !isLast ? '1px solid var(--color-border)' : 'none',
      background: 'var(--color-bg)',
    }}>
      {/* Строка проекта */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontWeight: 500, fontSize: 14, marginBottom: 3 }}>{project.name}</div>
          <div style={{ fontSize: 12, color: 'var(--color-text-muted)', display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
            <span>{project.file_count} файлов</span>
            <span style={{ padding: '1px 6px', borderRadius: 4, background: 'var(--color-surface)', fontSize: 11 }}>
              {project.project_type}
            </span>
            {project.has_graph ? (
              <span style={{ color: 'var(--color-success, #1d9e75)' }}>
                🕸 {project.graph_stats.nodes ?? 0} нод · {project.graph_stats.communities ?? 0} кластеров
              </span>
            ) : (
              <span style={{ opacity: 0.6 }}>— граф не построен</span>
            )}
          </div>
        </div>

        <div style={{ display: 'flex', gap: 6, flexShrink: 0 }}>
          <button
            onClick={isScanningThis ? onCancelScan : onScan}
            disabled={isAnyBusy && !isScanningThis}
            title={isScanningThis ? 'Остановить' : 'Переиндексировать'}
            style={iconBtn(isScanningThis ? '#d85a30' : undefined, isAnyBusy && !isScanningThis)}
          >
            {isScanningThis ? '⏹' : '↺'}
          </button>
          <button onClick={onDelete} disabled={isAnyBusy} style={iconBtn('var(--color-error, #a32d2d)', isAnyBusy)} title="Удалить">
            🗑
          </button>
        </div>
      </div>

      {/* Прогресс сканирования */}
      {isScanningThis && (
        <div style={{ marginTop: 10 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: 'var(--color-text-muted)', marginBottom: 4 }}>
            <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '70%' }}>
              {scanFile || 'Сканирую...'}
            </span>
            <span>{scanProgress}%</span>
          </div>
          <ProgressBar value={scanProgress} color="var(--color-accent)" />
        </div>
      )}

      {/* GraphRAG секция */}
      {!project.has_graph && !isBuildingThis && (
        <div style={{ marginTop: 10, display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          {estimate ? (
            <>
              <span style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>
                ~{estimate.estimated_tokens.toLocaleString()} токенов · {estimate.estimated_cost_display}
              </span>
              <button
                onClick={onBuildGraph}
                disabled={isAnyBusy}
                style={{ padding: '4px 12px', borderRadius: 6, border: '1px solid var(--color-border)', background: 'var(--color-accent-light)', color: 'var(--color-accent)', fontSize: 12, cursor: isAnyBusy ? 'not-allowed' : 'pointer' }}
              >
                🕸 Построить граф
              </button>
            </>
          ) : (
            <button onClick={onEstimate} style={{ padding: '4px 12px', borderRadius: 6, border: '1px solid var(--color-border)', background: 'transparent', color: 'var(--color-text-muted)', fontSize: 12, cursor: 'pointer' }}>
              Оценить стоимость графа
            </button>
          )}
        </div>
      )}

      {/* Прогресс построения графа */}
      {isBuildingThis && (
        <div style={{ marginTop: 10 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: 'var(--color-text-muted)', marginBottom: 4 }}>
            <span>{phaseLabel(graphPhase)}</span>
            {graphProgress > 0 && <span>{graphProgress}%</span>}
          </div>
          {graphProgress > 0 && <ProgressBar value={graphProgress} color="#1d9e75" />}
          <button onClick={onCancelGraph} style={{ marginTop: 6, padding: '3px 10px', borderRadius: 5, border: '1px solid var(--color-border)', background: 'transparent', color: 'var(--color-text-muted)', fontSize: 11, cursor: 'pointer' }}>
            Отменить
          </button>
        </div>
      )}

      {/* Результат построения графа */}
      {graphResult && project.name === project.name && (
        <div style={{ marginTop: 8, fontSize: 12, color: 'var(--color-success, #1d9e75)' }}>
          ✅ Граф готов: {graphResult.nodes} нод · {graphResult.edges} рёбер · {graphResult.communities} кластеров
        </div>
      )}
    </div>
  )
}

// ── Sub-components ────────────────────────────────────────────────────────────

function ProgressBar({ value, color }: { value: number; color: string }) {
  return (
    <div style={{ height: 4, background: 'var(--color-surface)', borderRadius: 2, overflow: 'hidden' }}>
      <div style={{ height: '100%', width: `${value}%`, background: color, borderRadius: 2, transition: 'width 0.3s' }} />
    </div>
  )
}

function phaseLabel(phase: string): string {
  return ({
    entity_extraction:   '🔍 Извлечение сущностей...',
    community_detection: '🔗 Кластеризация...',
    community_summaries: '📝 Генерация резюме...',
  } as Record<string, string>)[phase] ?? 'Обрабатываю...'
}

// ── Стили ─────────────────────────────────────────────────────────────────────

const primaryBtn: React.CSSProperties = {
  padding: '7px 14px', borderRadius: 7, border: 'none',
  background: 'var(--color-accent)', color: '#fff', fontSize: 13, cursor: 'pointer',
}

const inputStyle: React.CSSProperties = {
  flex: 1, padding: '7px 10px', borderRadius: 6,
  border: '1px solid var(--color-border)',
  background: 'var(--color-bg)', color: 'var(--color-text)', fontSize: 13,
}

const errorBox: React.CSSProperties = {
  padding: '10px 14px', borderRadius: 8, fontSize: 13,
  background: 'rgba(210,90,48,0.08)', border: '1px solid rgba(210,90,48,0.25)',
  color: 'var(--color-error, #a32d2d)', display: 'flex',
  justifyContent: 'space-between', alignItems: 'center',
}

function iconBtn(color?: string, disabled = false): React.CSSProperties {
  return {
    padding: '5px 9px', borderRadius: 6,
    border: '1px solid var(--color-border)', background: 'transparent',
    color: color ?? 'var(--color-text-muted)', fontSize: 14,
    cursor: disabled ? 'not-allowed' : 'pointer',
    opacity: disabled ? 0.4 : 1,
  }
}
