/**
 * useJobEvents — subscribe to a job's SSE stream.
 *
 * The browser's native EventSource handles reconnection automatically
 * (sends Last-Event-ID back). We use a ref-stored last-id so retries
 * after manual reset start at the right cursor.
 *
 * Returns the accumulated event list + a `terminal` boolean that flips
 * when the backend sends `job_completed` or `job_failed`. The caller
 * (JobDetail page) listens to that to invalidate the job-detail query
 * and stop showing the live indicator.
 */
import { useEffect, useRef, useState } from "react"

export interface JobEvent {
  /** Backend-assigned event id (Last-Event-ID cursor). */
  id: number | null
  kind: string
  ts: string
  // The bus serialises the full payload into data — we keep it as a
  // record so the renderer can pick out interesting fields per kind
  // (node, query, round, todos done/pending).
  payload: Record<string, unknown>
}

export function useJobEvents(jobId: string | undefined) {
  const [events, setEvents] = useState<JobEvent[]>([])
  const [terminal, setTerminal] = useState(false)
  const [connected, setConnected] = useState(false)
  const esRef = useRef<EventSource | null>(null)

  useEffect(() => {
    if (!jobId) return
    // Reset state on jobId change.
    setEvents([])
    setTerminal(false)

    const url = `/api/jobs/${jobId}/events`
    const es = new EventSource(url)
    esRef.current = es

    es.onopen = () => setConnected(true)
    es.onerror = () => setConnected(false)

    // SSE dispatches via the event NAME, not the default "message".
    // We listen on "message" for unnamed events and add named ones
    // dynamically. The backend always names events by `kind`, but we
    // also handle the generic case.
    const handle = (e: MessageEvent<string>) => {
      // `ping` keepalive events have empty data — skip them.
      if (!e.data) return
      let parsed: Record<string, unknown>
      try {
        parsed = JSON.parse(e.data)
      } catch {
        return
      }
      const kind = String(parsed.kind ?? e.type ?? "info")
      const ts = String(parsed.ts ?? new Date().toISOString())
      const ev: JobEvent = {
        id: e.lastEventId ? Number(e.lastEventId) : null,
        kind,
        ts,
        payload: parsed,
      }
      setEvents((prev) => [...prev, ev])
      if (kind === "job_completed" || kind === "job_failed") {
        setTerminal(true)
        es.close()
      }
    }

    // Register handlers for every event name the backend emits.
    // Listening on "message" alone misses named events.
    const names = [
      "message",
      "job_started", "job_completed", "job_failed",
      "node_start", "node_end",
      "search_batch", "search_query", "evaluate",
      "info", "warning", "error",
    ]
    names.forEach((n) => es.addEventListener(n, handle as EventListener))

    return () => {
      names.forEach((n) => es.removeEventListener(n, handle as EventListener))
      es.close()
      esRef.current = null
    }
  }, [jobId])

  return { events, terminal, connected }
}
