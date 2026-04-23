import { useCallback, useRef, useState } from 'react'

export type SSEStatus = 'idle' | 'streaming' | 'done' | 'error'

interface UseSSEOptions<T> {
  /** Вызывается для каждого события из потока */
  onEvent: (event: T) => void
  /** Вызывается когда поток завершён (type === 'done') */
  onDone?: () => void
  /** Вызывается при ошибке */
  onError?: (message: string, requestId?: string) => void
}

interface UseSSEResult {
  status: SSEStatus
  /** Запустить SSE поток. Возвращает функцию отмены. */
  start: (fetcher: () => Promise<Response>) => void
  /** Отменить текущий поток */
  cancel: () => void
  /** requestId из последнего ответа (для диагностики) */
  requestId: string | null
}

/**
 * Хук для работы с SSE потоками.
 *
 * Гарантирует:
 * - Правильный cleanup при размонтировании компонента
 * - Парсинг SSE формата `data: {...}\n\n`
 * - Обработку network ошибок
 * - Обработку `{type: 'error'}` событий из бэкенда
 * - Нет race conditions (abort предыдущего потока при новом start)
 *
 * Использование:
 *   const { status, start, cancel } = useSSE<SearchEvent>({
 *     onEvent: (event) => { ... },
 *     onDone: () => setLoading(false),
 *   })
 *
 *   start(() => fetch('/api/search/answer', { method: 'POST', ... }))
 */
export function useSSE<T extends { type: string }>(
  options: UseSSEOptions<T>
): UseSSEResult {
  const [status, setStatus] = useState<SSEStatus>('idle')
  const [requestId, setRequestId] = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)
  const optionsRef = useRef(options)
  optionsRef.current = options  // Всегда актуальные callbacks без ре-рендера

  const cancel = useCallback(() => {
    abortRef.current?.abort()
    abortRef.current = null
    setStatus(prev => prev === 'streaming' ? 'idle' : prev)
  }, [])

  const start = useCallback((fetcher: () => Promise<Response>) => {
    // Отменяем предыдущий поток если есть
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    setStatus('streaming')
    setRequestId(null)

    const run = async () => {
      let response: Response

      try {
        response = await fetcher()
      } catch (err) {
        if ((err as Error).name === 'AbortError') return
        setStatus('error')
        optionsRef.current.onError?.('Не удалось подключиться к серверу')
        return
      }

      // Сохраняем request_id для диагностики
      const rid = response.headers.get('X-Request-ID')
      if (rid) setRequestId(rid)

      if (!response.ok || !response.body) {
        setStatus('error')
        optionsRef.current.onError?.(
          `HTTP ${response.status}: ${response.statusText}`,
          rid ?? undefined
        )
        return
      }

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      try {
        while (true) {
          const { done, value } = await reader.read()
          if (done) break

          buffer += decoder.decode(value, { stream: true })

          // SSE: события разделяются двойным переносом строки
          const parts = buffer.split('\n\n')
          buffer = parts.pop() ?? ''  // Последний фрагмент может быть неполным

          for (const part of parts) {
            const line = part.trim()
            if (!line.startsWith('data: ')) continue

            let event: T
            try {
              event = JSON.parse(line.slice(6)) as T
            } catch {
              console.warn('[useSSE] Невалидный JSON:', line.slice(6, 100))
              continue
            }

            // Бэкенд сигнализирует об ошибке через type: 'error'
            if (event.type === 'error') {
              const errEvent = event as unknown as { message?: string; request_id?: string }
              setStatus('error')
              optionsRef.current.onError?.(
                errEvent.message ?? 'Ошибка на сервере',
                errEvent.request_id ?? rid ?? undefined
              )
              return
            }

            optionsRef.current.onEvent(event)

            if (event.type === 'done') {
              setStatus('done')
              optionsRef.current.onDone?.()
              return
            }
          }
        }
      } catch (err) {
        if ((err as Error).name === 'AbortError') return
        setStatus('error')
        optionsRef.current.onError?.(`Ошибка чтения потока: ${(err as Error).message}`)
      } finally {
        reader.releaseLock()
      }

      // Поток завершился без события 'done' — считаем завершённым
      if (status === 'streaming') {
        setStatus('done')
        optionsRef.current.onDone?.()
      }
    }

    run()
  }, [])  // eslint-disable-line react-hooks/exhaustive-deps

  return { status, start, cancel, requestId }
}
