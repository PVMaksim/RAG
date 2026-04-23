'use client'

import dynamic from 'next/dynamic'
import { useEffect, useRef, useState } from 'react'
import { fetchGraph, type GraphData, type GraphNode } from '@/lib/api'
import { useProjects } from '@/hooks/useProjects'
import { ErrorBoundary } from '@/components/ErrorBoundary'

// react-force-graph использует window → импортируем без SSR
const ForceGraph2D = dynamic(
  () => import('react-force-graph-2d'),
  { ssr: false, loading: () => <GraphPlaceholder text="Загружаю граф..." /> }
)

// Цвета по типу ноды
const NODE_COLORS: Record<string, string> = {
  function:    '#7f77dd',
  class:       '#534ab7',
  module:      '#1d9e75',
  config:      '#ef9f27',
  entrypoint:  '#d85a30',
  documentation: '#3b8bd4',
}

// Цвета по community (циклически)
const COMMUNITY_COLORS = [
  '#7f77dd', '#1d9e75', '#ef9f27', '#3b8bd4',
  '#d85a30', '#d4537e', '#639922', '#ba7517',
]

export default function GraphPage() {
  return (
    <ErrorBoundary>
      <GraphContent />
    </ErrorBoundary>
  )
}

function GraphContent() {
  const { projects, reload: reloadProjects } = useProjects()
  const [selectedProject, setSelected] = useState<string>('')
  const [graphData, setGraphData]       = useState<GraphData | null>(null)
  const [loading, setLoading]           = useState(false)
  const [error, setError]               = useState<string | null>(null)
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null)
  const [colorBy, setColorBy]           = useState<'type' | 'community'>('community')
  const [filterType, setFilterType]     = useState<string>('all')
  const [nodeSearch, setNodeSearch]     = useState<string>('')
  const graphRef = useRef<unknown>(null)

  useEffect(() => {
    // Автовыбор первого проекта с графом
    const withGraph = projects.find(p => p.has_graph)
    if (withGraph && !selectedProject) setSelected(withGraph.name)
  }, [projects])

  useEffect(() => {
    if (selectedProject === undefined) return
    setLoading(true)
    setError(null)
    setSelectedNode(null)

    fetchGraph(selectedProject || undefined)
      .then(data => { setGraphData(data); setLoading(false) })
      .catch(err => {
        setError(err.message?.includes('404')
          ? 'Knowledge Graph не построен. Перейди в «Проекты» и нажми «Построить граф знаний».'
          : String(err))
        setLoading(false)
      })
  }, [selectedProject])

  // Фильтрация нод по типу
  const visibleData = graphData ? (() => {
    let nodes = filterType === 'all'
      ? graphData.nodes
      : graphData.nodes.filter(n => n.type === filterType)
    if (nodeSearch.trim()) {
      const q = nodeSearch.toLowerCase()
      nodes = nodes.filter(n =>
        n.name.toLowerCase().includes(q) ||
        n.file.toLowerCase().includes(q) ||
        n.description?.toLowerCase().includes(q)
      )
    }
    return { nodes, links: graphData.links }
  })() : { nodes: [], links: [] }

  const nodeTypes = graphData
    ? [...new Set(graphData.nodes.map(n => n.type))]
    : []

  const getNodeColor = (node: GraphNode) => {
    if (colorBy === 'community' && node.community !== null && node.community !== undefined) {
      return COMMUNITY_COLORS[node.community % COMMUNITY_COLORS.length]
    }
    return NODE_COLORS[node.type] ?? '#888780'
  }

  const handleNodeClick = (node: unknown) => {
    setSelectedNode(node as GraphNode)
  }

  const focusNode = (nodeId: string) => {
    if (!graphRef.current) return
    const node = graphData?.nodes.find(n => n.id === nodeId)
    if (node) {
      // @ts-ignore
      graphRef.current.centerAt(node.x, node.y, 800)
      // @ts-ignore
      graphRef.current.zoom(4, 800)
    }
  }

  return (
    <div style={{ height: 'calc(100vh - 48px)', display: 'flex', flexDirection: 'column', gap: 0 }}>

      {/* Тулбар */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        padding: '0 0 14px',
        flexWrap: 'wrap',
      }}>
        <h1 style={{ fontSize: 18, fontWeight: 500, marginRight: 4 }}>Knowledge Graph</h1>

        {/* Выбор проекта */}
        <select
          value={selectedProject}
          onChange={e => setSelected(e.target.value)}
          style={selectStyle}
        >
          <option value="">Все проекты</option>
          {projects.filter(p => p.has_graph).map(p => (
            <option key={p.name} value={p.name}>{p.name}</option>
          ))}
        </select>
        <button
          onClick={() => { reloadProjects(); if (selectedProject) setGraphData(null) }}
          title="Обновить список проектов"
          style={{ ...selectStyle, cursor: 'pointer' }}
        >
          ↺
        </button>

        {/* Цвет по */}
        <select value={colorBy} onChange={e => setColorBy(e.target.value as 'type' | 'community')} style={selectStyle}>
          <option value="community">Цвет: кластер</option>
          <option value="type">Цвет: тип</option>
        </select>

        {/* Фильтр по типу */}
        {nodeTypes.length > 0 && (
          <select value={filterType} onChange={e => setFilterType(e.target.value)} style={selectStyle}>
            <option value="all">Все типы</option>
            {nodeTypes.map(t => <option key={t} value={t}>{t}</option>)}
          </select>
        )}

        {/* Поиск по нодам */}
        <input
          value={nodeSearch}
          onChange={e => setNodeSearch(e.target.value)}
          placeholder="Поиск нод..."
          style={{ ...selectStyle, width: 160, cursor: 'text' }}
        />

        {/* Кнопка Zoom to fit */}
        {graphData && (
          <button
            onClick={() => {
              // @ts-ignore
              graphRef.current?.zoomToFit(400, 40)
            }}
            title="Показать весь граф"
            style={{ ...selectStyle, cursor: 'pointer' }}
          >
            ⊡
          </button>
        )}

        {/* Экспорт графа в JSON */}
        {graphData && (
          <button
            onClick={() => {
              const blob = new Blob(
                [JSON.stringify(graphData, null, 2)],
                { type: 'application/json' }
              )
              const url = URL.createObjectURL(blob)
              const a = document.createElement('a')
              a.href = url
              a.download = `${selectedProject || 'all'}-graph-${new Date().toISOString().slice(0,10)}.json`
              a.click()
              URL.revokeObjectURL(url)
            }}
            title="Экспорт графа в JSON"
            style={{ ...selectStyle, cursor: 'pointer' }}
          >
            ↓ JSON
          </button>
        )}

        {/* Статистика */}
        {graphData && (
          <span style={{ marginLeft: 'auto', fontSize: 12, color: 'var(--color-text-muted)' }}>
            {visibleData.nodes.length}{nodeSearch ? `/${graphData.nodes.length}` : ''} нод · {graphData.links.length} рёбер · {graphData.communities.length} кластеров
          </span>
        )}
      </div>

      {/* Основная область */}
      <div style={{ flex: 1, display: 'flex', gap: 12, minHeight: 0 }}>

        {/* Граф */}
        <div style={{
          flex: 1,
          border: '1px solid var(--color-border)',
          borderRadius: 10,
          overflow: 'hidden',
          position: 'relative',
          background: 'var(--color-surface)',
          minHeight: 400,
        }}>
          {loading && <GraphPlaceholder text="Загружаю..." />}
          {error && <GraphPlaceholder text={error} isError />}

          {!loading && !error && graphData && visibleData.nodes.length > 0 && (
            <ForceGraph2D
              ref={graphRef}
              graphData={visibleData}
              nodeLabel={(node: unknown) => {
                const n = node as GraphNode
                return `${n.name} (${n.type})\n${n.file}`
              }}
              nodeColor={(node: unknown) => getNodeColor(node as GraphNode)}
              nodeRelSize={4}
              nodeVal={(node: unknown) => {
                // Размер ноды: entrypoint — крупнее
                const n = node as GraphNode
                return n.type === 'entrypoint' ? 3 : n.type === 'class' ? 2 : 1
              }}
              linkColor={() => 'rgba(128,128,128,0.3)'}
              linkWidth={0.8}
              linkDirectionalArrowLength={3}
              linkDirectionalArrowRelPos={1}
              onNodeClick={handleNodeClick}
              backgroundColor="transparent"
              width={undefined}
              height={undefined}
            />
          )}

          {!loading && !error && (!graphData || visibleData.nodes.length === 0) && (
            <GraphPlaceholder text={
              projects.every(p => !p.has_graph)
                ? 'Граф не построен ни для одного проекта'
                : 'Нет нод для отображения'
            } />
          )}

          {/* Легенда */}
          {graphData && (
            <div style={{
              position: 'absolute',
              bottom: 12,
              left: 12,
              background: 'var(--color-bg)',
              border: '1px solid var(--color-border)',
              borderRadius: 8,
              padding: '8px 12px',
              fontSize: 11,
            }}>
              {colorBy === 'type'
                ? Object.entries(NODE_COLORS).map(([type, color]) => (
                    <div key={type} style={{ display: 'flex', alignItems: 'center', gap: 5, marginBottom: 2 }}>
                      <span style={{ width: 8, height: 8, borderRadius: '50%', background: color, flexShrink: 0 }} />
                      <span style={{ color: 'var(--color-text-muted)' }}>{type}</span>
                    </div>
                  ))
                : graphData.communities.slice(0, 6).map((c, i) => (
                    <div key={c.id} style={{ display: 'flex', alignItems: 'center', gap: 5, marginBottom: 2 }}>
                      <span style={{ width: 8, height: 8, borderRadius: '50%', background: COMMUNITY_COLORS[i % COMMUNITY_COLORS.length], flexShrink: 0 }} />
                      <span style={{ color: 'var(--color-text-muted)', maxWidth: 120, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{c.title}</span>
                    </div>
                  ))
              }
            </div>
          )}
        </div>

        {/* Панель деталей выбранной ноды */}
        {selectedNode && (
          <div style={{
            width: 260,
            border: '1px solid var(--color-border)',
            borderRadius: 10,
            padding: 14,
            display: 'flex',
            flexDirection: 'column',
            gap: 10,
            background: 'var(--color-bg)',
            overflowY: 'auto',
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
              <div style={{ fontWeight: 500, fontSize: 14, wordBreak: 'break-word' }}>{selectedNode.name}</div>
              <button
                onClick={() => setSelectedNode(null)}
                style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--color-text-muted)', fontSize: 16, flexShrink: 0 }}
              >×</button>
            </div>

            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              <Tag label={selectedNode.type} color="accent" />
              <Tag label={selectedNode.project} color="muted" />
              {selectedNode.community !== null && (
                <Tag label={`кластер ${selectedNode.community}`} color="muted" />
              )}
            </div>

            {selectedNode.file && (
              <div>
                <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginBottom: 3 }}>Файл</div>
                <div style={{ fontSize: 12, fontFamily: 'monospace', wordBreak: 'break-all', color: 'var(--color-text)' }}>
                  {selectedNode.file}
                </div>
              </div>
            )}

            {selectedNode.description && (
              <div>
                <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginBottom: 3 }}>Описание</div>
                <div style={{ fontSize: 12, lineHeight: 1.5 }}>{selectedNode.description}</div>
              </div>
            )}

            {/* Связанные ноды */}
            {graphData && (() => {
              const related = graphData.links
                .filter(l => l.source === selectedNode.id || l.target === selectedNode.id)
                .slice(0, 8)
              if (!related.length) return null
              return (
                <div>
                  <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginBottom: 6 }}>Связи ({related.length})</div>
                  {related.map((link, i) => {
                    const isSource = link.source === selectedNode.id
                    const otherId = isSource ? link.target : link.source
                    const other = graphData.nodes.find(n => n.id === otherId)
                    return (
                      <button
                        key={i}
                        onClick={() => {
                          const n = graphData.nodes.find(x => x.id === otherId)
                          if (n) { setSelectedNode(n); focusNode(n.id) }
                        }}
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          gap: 6,
                          padding: '5px 0',
                          borderBottom: '1px solid var(--color-border)',
                          background: 'none',
                          border: 'none',
                          cursor: 'pointer',
                          width: '100%',
                          textAlign: 'left',
                          color: 'var(--color-text)',
                        }}
                      >
                        <span style={{ fontSize: 10, color: 'var(--color-text-muted)', minWidth: 36 }}>
                          {isSource ? '→' : '←'} {link.relation}
                        </span>
                        <span style={{ fontSize: 12, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                          {other?.name ?? otherId.slice(0, 8)}
                        </span>
                      </button>
                    )
                  })}
                </div>
              )
            })()}
          </div>
        )}
      </div>
    </div>
  )
}

function GraphPlaceholder({ text, isError = false }: { text: string; isError?: boolean }) {
  return (
    <div style={{
      position: 'absolute', inset: 0,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      flexDirection: 'column', gap: 10,
      color: isError ? 'var(--color-error)' : 'var(--color-text-muted)',
      fontSize: 13, textAlign: 'center', padding: 24,
    }}>
      <span style={{ fontSize: 32 }}>{isError ? '⚠️' : '🕸'}</span>
      {text}
    </div>
  )
}

function Tag({ label, color }: { label: string; color: 'accent' | 'muted' }) {
  return (
    <span style={{
      padding: '2px 7px',
      borderRadius: 4,
      fontSize: 11,
      background: color === 'accent' ? 'var(--color-accent-light)' : 'var(--color-surface)',
      color: color === 'accent' ? 'var(--color-accent)' : 'var(--color-text-muted)',
    }}>{label}</span>
  )
}

const selectStyle: React.CSSProperties = {
  padding: '5px 10px',
  borderRadius: 6,
  border: '1px solid var(--color-border)',
  background: 'var(--color-surface)',
  color: 'var(--color-text)',
  fontSize: 12,
  cursor: 'pointer',
}
