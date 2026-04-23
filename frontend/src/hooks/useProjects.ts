import { useCallback, useEffect, useRef, useState } from 'react'
import { deleteProject, estimateGraphCost, fetchProjects, type Project } from '@/lib/api'

interface UseProjectsResult {
  projects: Project[]
  loading: boolean
  error: string | null
  reload: () => Promise<void>
  remove: (name: string) => Promise<void>
  getEstimate: (name: string) => Promise<void>
  estimates: Record<string, { estimated_tokens: number; estimated_cost_display: string }>
}

/**
 * Хук управления проектами.
 * Инкапсулирует загрузку, удаление, оценку стоимости графа.
 * Оптимистичное обновление при удалении (не ждём сервер для UI).
 */
export function useProjects(): UseProjectsResult {
  const [projects, setProjects]   = useState<Project[]>([])
  const [loading, setLoading]     = useState(true)
  const [error, setError]         = useState<string | null>(null)
  const [estimates, setEstimates] = useState<Record<string, {
    estimated_tokens: number
    estimated_cost_display: string
  }>>({})

  const reload = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const list = await fetchProjects()
      setProjects(list)
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Не удалось загрузить проекты'
      setError(msg)
      console.error('[useProjects] fetch error:', err)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { reload() }, [reload])

  const remove = useCallback(async (name: string) => {
    // Оптимистичное удаление — убираем из UI сразу
    setProjects(prev => prev.filter(p => p.name !== name))
    try {
      await deleteProject(name)
    } catch (err) {
      // Откатываем если сервер вернул ошибку
      console.error('[useProjects] delete error:', err)
      await reload()
      throw err
    }
  }, [reload])

  const getEstimate = useCallback(async (name: string) => {
    try {
      const est = await estimateGraphCost(name)
      setEstimates(prev => ({ ...prev, [name]: est }))
    } catch (err) {
      console.error('[useProjects] estimate error:', err)
    }
  }, [])

  return { projects, loading, error, reload, remove, getEstimate, estimates }
}
