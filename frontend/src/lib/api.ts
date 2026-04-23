/**
 * api.ts — HTTP клиент к FastAPI бэкенду.
 * Все вызовы к /api/* проходят через nginx → backend.
 */

const BASE = process.env.NEXT_PUBLIC_API_URL ?? '/api'

// ── Типы ──────────────────────────────────────────────────────────────────────

export interface Chunk {
  project: string
  file: string
  role: string
  score: number
  content_preview: string
}

export interface Project {
  name: string
  file_count: number
  project_type: string
  has_graph: boolean
  graph_stats: { nodes?: number; edges?: number; communities?: number }
}

export interface GraphData {
  nodes: GraphNode[]
  links: GraphLink[]
  stats: { nodes: number; edges: number; communities: number }
  communities: { id: number; title: string; node_count: number }[]
}

export interface GraphNode {
  id: string
  name: string
  type: string
  file: string
  description: string
  community: number | null
  project: string
}

export interface GraphLink {
  source: string
  target: string
  relation: string
  weight: number
}

export type SearchMode = 'search' | 'answer' | 'patch' | 'global'

// ── SSE стриминг ──────────────────────────────────────────────────────────────

/**
 * Открывает SSE поток и вызывает onEvent для каждого события.
 * Возвращает функцию для отмены (abort).
 */
export function streamSearch(
  query: string,
  mode: SearchMode,
  project: string | null,
  topK: number,
  onEvent: (event: Record<string, unknown>) => void,
): () => void {
  const controller = new AbortController()

  const endpoint =
    mode === 'global' ? `${BASE}/search/global`
    : mode === 'patch' ? `${BASE}/search/patch`
    : mode === 'answer' ? `${BASE}/search/answer`
    : `${BASE}/search/`

  fetch(endpoint, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, project, top_k: topK, mode }),
    signal: controller.signal,
  })
    .then(async (res) => {
      if (!res.ok || !res.body) {
        onEvent({ type: 'error', message: `HTTP ${res.status}` })
        return
      }
      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        // SSE: каждая строка "data: {...}\n\n"
        const lines = buffer.split('\n\n')
        buffer = lines.pop() ?? ''
        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              onEvent(JSON.parse(line.slice(6)))
            } catch { /* skip malformed */ }
          }
        }
      }
    })
    .catch((err) => {
      if (err.name !== 'AbortError') {
        onEvent({ type: 'error', message: String(err) })
      }
    })

  return () => controller.abort()
}

// ── Проекты ───────────────────────────────────────────────────────────────────

export async function fetchProjects(): Promise<Project[]> {
  const res = await fetch(`${BASE}/projects/`)
  if (!res.ok) throw new Error(`Failed to fetch projects: ${res.status}`)
  const data = await res.json()
  return data.projects
}

export async function deleteProject(name: string): Promise<void> {
  const res = await fetch(`${BASE}/projects/${name}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(`Failed to delete project: ${res.status}`)
}

/** Создаёт fetcher для useSSE хука — сканирование проекта по пути */
export function makeScanFetcher(projectName: string, projectPath: string): () => Promise<Response> {
  return () => fetch(`${BASE}/projects/${projectName}/scan-path`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path: projectPath }),
  })
}

/** Создаёт fetcher для useSSE хука — клонирование Git репозитория */
export function makeGitCloneFetcher(gitUrl: string, projectName?: string): () => Promise<Response> {
  return () => fetch(`${BASE}/projects/git/clone`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ git_url: gitUrl, project_name: projectName }),
  })
}

export async function estimateGraphCost(projectName: string) {
  const res = await fetch(`${BASE}/projects/${projectName}/graph/estimate`)
  if (!res.ok) throw new Error(`Failed to estimate: ${res.status}`)
  return res.json()
}

/** Создаёт fetcher для useSSE хука — построение Knowledge Graph */
export function makeGraphBuildFetcher(projectName: string): () => Promise<Response> {
  return () => fetch(`${BASE}/projects/${projectName}/graph/build`, { method: 'POST' })
}

// ── Граф ──────────────────────────────────────────────────────────────────────

export async function fetchGraph(project?: string): Promise<GraphData> {
  const url = project ? `${BASE}/graph/${project}` : `${BASE}/graph/`
  const res = await fetch(url)
  if (!res.ok) throw new Error(`Failed to fetch graph: ${res.status}`)
  return res.json()
}

// ── Health ─────────────────────────────────────────────────────────────────────

export async function fetchHealth() {
  const res = await fetch('/health')
  if (!res.ok) throw new Error('Backend unavailable')
  return res.json()
}

// ── Upload API ────────────────────────────────────────────────────────────────

/** Создаёт fetcher для useSSE — загрузка ZIP архива */
export function makeUploadFetcher(file: File, projectName?: string): () => Promise<Response> {
  return () => {
    const form = new FormData()
    form.append('file', file)
    if (projectName) form.append('project_name', projectName)
    return fetch(`${BASE}/upload/zip`, { method: 'POST', body: form })
  }
}

export async function fetchUploadLimits(): Promise<{
  max_zip_size_mb: number
  max_files: number
  rate_limit: string
}> {
  const res = await fetch(`${BASE}/upload/limits`)
  if (!res.ok) throw new Error(`Failed to fetch upload limits: ${res.status}`)
  return res.json()
}

// ── Webhook ───────────────────────────────────────────────────────────────────

export async function testWebhook(): Promise<{ status: string; message: string }> {
  const res = await fetch(`${BASE}/webhook/github`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-GitHub-Event': 'ping',
      // В реальности GitHub подписывает запрос HMAC
    },
    body: JSON.stringify({ zen: 'test ping' }),
  })
  return res.json()
}

/** Создаёт fetcher для useSSE — git pull + переиндексирование */
export function makeGitPullFetcher(projectName: string): () => Promise<Response> {
  return () => fetch(`${BASE}/projects/git/pull/${projectName}`, { method: 'POST' })
}
