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
  const graphRef = useRef<any>(null)

  useEffect(() => {
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
    <div className="h-[calc(100vh-48px)] flex flex-col">

      {/* Тулбар */}
      <div className="flex items-center gap-2.5 pb-3.5 flex-wrap">
        <h1 className="text-base font-medium mr-1">Knowledge Graph</h1>

        <select
          value={selectedProject}
          onChange={e => setSelected(e.target.value)}
          className="px-2.5 py-1.5 rounded-md border border-gray-300 bg-white text-sm cursor-pointer"
        >
          <option value="">Все проекты</option>
          {projects.filter(p => p.has_graph).map(p => (
            <option key={p.name} value={p.name}>{p.name}</option>
          ))}
        </select>
        
        <button
          onClick={() => { reloadProjects(); if (selectedProject) setGraphData(null) }}
          title="Обновить список проектов"
          className="px-2.5 py-1.5 rounded-md border border-gray-300 bg-white text-sm cursor-pointer"
        >
          ↺
        </button>

        <select 
          value={colorBy} 
          onChange={e => setColorBy(e.target.value as 'type' | 'community')} 
          className="px-2.5 py-1.5 rounded-md border border-gray-300 bg-white text-sm cursor-pointer"
        >
          <option value="community">Цвет: кластер</option>
          <option value="type">Цвет: тип</option>
        </select>

        {nodeTypes.length > 0 && (
          <select 
            value={filterType} 
            onChange={e => setFilterType(e.target.value)} 
            className="px-2.5 py-1.5 rounded-md border border-gray-300 bg-white text-sm cursor-pointer"
          >
            <option value="all">Все типы</option>
            {nodeTypes.map(t => <option key={t} value={t}>{t}</option>)}
          </select>
        )}

        <input
          value={nodeSearch}
          onChange={e => setNodeSearch(e.target.value)}
          placeholder="Поиск нод..."
          className="px-2.5 py-1.5 rounded-md border border-gray-300 bg-white text-sm w-40 cursor-text"
        />

        {graphData && (
          <button
            onClick={() => {
              // @ts-ignore
              graphRef.current?.zoomToFit(400, 40)
            }}
            title="Показать весь граф"
            className="px-2.5 py-1.5 rounded-md border border-gray-300 bg-white text-sm cursor-pointer"
          >
            ⊡
          </button>
        )}

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
            className="px-2.5 py-1.5 rounded-md border border-gray-300 bg-white text-sm cursor-pointer"
          >
            ↓ JSON
          </button>
        )}

        {graphData && (
          <span className="ml-auto text-xs text-gray-500">
            {visibleData.nodes.length}{nodeSearch ? `/${graphData.nodes.length}` : ''} нод · {graphData.links.length} рёбер · {graphData.communities.length} кластеров
          </span>
        )}
      </div>

      {/* Основная область */}
      <div className="flex-1 flex gap-3 min-h-0">

        {/* Граф */}
        <div className="flex-1 border border-gray-300 rounded-xl overflow-hidden relative bg-gray-50 min-h-[400px]">
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
            <div className="absolute bottom-3 left-3 bg-white border border-gray-300 rounded-lg p-2 text-xs">
              {colorBy === 'type'
                ? Object.entries(NODE_COLORS).map(([type, color]) => (
                    <div key={type} className="flex items-center gap-1.5 mb-0.5">
                      <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: color }} />
                      <span className="text-gray-500">{type}</span>
                    </div>
                  ))
                : graphData.communities.slice(0, 6).map((c, i) => (
                    <div key={c.id} className="flex items-center gap-1.5 mb-0.5">
                      <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: COMMUNITY_COLORS[i % COMMUNITY_COLORS.length] }} />
                      <span className="text-gray-500 max-w-[120px] overflow-hidden text-ellipsis whitespace-nowrap">{c.title}</span>
                    </div>
                  ))
              }
            </div>
          )}
        </div>

        {/* Панель деталей */}
        {selectedNode && (
          <div className="w-64 border border-gray-300 rounded-xl p-3.5 flex flex-col gap-2.5 bg-white overflow-y-auto">
            <div className="flex justify-between items-start">
              <div className="font-medium text-sm break-words">{selectedNode.name}</div>
              <button
                onClick={() => setSelectedNode(null)}
                className="bg-none border-none cursor-pointer text-gray-500 text-base flex-shrink-0 hover:text-gray-700"
              >×</button>
            </div>

            <div className="flex gap-1.5 flex-wrap">
              <Tag label={selectedNode.type} color="accent" />
              <Tag label={selectedNode.project} color="muted" />
              {selectedNode.community !== null && (
                <Tag label={`кластер ${selectedNode.community}`} color="muted" />
              )}
            </div>

            {selectedNode.file && (
              <div>
                <div className="text-xs text-gray-500 mb-1">Файл</div>
                <div className="text-xs font-mono break-all text-gray-700">
                  {selectedNode.file}
                </div>
              </div>
            )}

            {selectedNode.description && (
              <div>
                <div className="text-xs text-gray-500 mb-1">Описание</div>
                <div className="text-xs leading-relaxed">{selectedNode.description}</div>
              </div>
            )}

            {graphData && (() => {
              const related = graphData.links
                .filter(l => l.source === selectedNode.id || l.target === selectedNode.id)
                .slice(0, 8)
              if (!related.length) return null
              return (
                <div>
                  <div className="text-xs text-gray-500 mb-1.5">Связи ({related.length})</div>
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
                        className="flex items-center gap-1.5 py-1.5 border-b border-gray-200 bg-none border-none cursor-pointer w-full text-left text-gray-700 hover:bg-gray-50 transition-colors"
                      >
                        <span className="text-[10px] text-gray-500 min-w-[36px]">
                          {isSource ? '→' : '←'} {link.relation}
                        </span>
                        <span className="text-xs overflow-hidden text-ellipsis whitespace-nowrap">
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
    <div className="absolute inset-0 flex items-center justify-center flex-col gap-2.5 text-gray-500 text-sm text-center p-6">
      <span className="text-2xl">{isError ? '⚠️' : '🕸'}</span>
      <span>{text}</span>
    </div>
  )
}

function Tag({ label, color }: { label: string; color: 'accent' | 'muted' }) {
  return (
    <span className={`px-1.5 py-0.5 rounded text-[10px] ${
      color === 'accent' 
        ? 'bg-blue-100 text-blue-600' 
        : 'bg-gray-100 text-gray-500'
    }`}>
      {label}
    </span>
  )
}