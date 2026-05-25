import { useParams } from "@tanstack/react-router"
import { useEffect, useRef } from "react"
import { format } from "date-fns"
import { useJob, useInvalidateJob } from "@/api/hooks"
import { useJobEvents, type JobEvent } from "@/api/useJobEvents"
import { api, type JobStatus } from "@/api/client"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { CheckpointGate } from "@/components/checkpoints/CheckpointGate"
import {
  AlertCircle, CheckCircle2, Clock, Download, FileText, Loader2,
  XCircle, Radio, PauseCircle,
} from "lucide-react"

/** Map status → Badge variant + icon + label. */
const STATUS_META: Record<JobStatus, { label: string; variant: "muted" | "success" | "destructive" | "warning"; icon: React.ComponentType<{ className?: string }> }> = {
  queued:               { label: "排隊中",    variant: "muted",       icon: Clock },
  running:              { label: "執行中",    variant: "warning",     icon: Loader2 },
  needs_confirm:        { label: "等待確認",  variant: "warning",     icon: PauseCircle },
  needs_subject_review: { label: "校稿中",    variant: "warning",     icon: PauseCircle },
  needs_slide_confirm:  { label: "確認投影片", variant: "warning",     icon: PauseCircle },
  done:                 { label: "完成",      variant: "success",     icon: CheckCircle2 },
  failed:               { label: "失敗",      variant: "destructive", icon: XCircle },
  cancelled:            { label: "已取消",    variant: "muted",       icon: XCircle },
}

export function JobDetailPage() {
  const { jobId } = useParams({ from: "/jobs/$jobId" })
  const { data: job, isLoading } = useJob(jobId)
  const { events, terminal, connected } = useJobEvents(jobId)
  const invalidate = useInvalidateJob()

  // When the SSE stream sends a terminal event, refetch the job row so
  // status / cost / output_path reflect the final state.
  useEffect(() => {
    if (terminal && jobId) invalidate(jobId)
  }, [terminal, jobId, invalidate])

  const handleDownload = async () => {
    if (!jobId) return
    const { blob, filename } = await api.downloadOutput(jobId)
    const url = URL.createObjectURL(blob)
    const a = document.createElement("a")
    a.href = url
    a.download = filename
    a.click()
    URL.revokeObjectURL(url)
  }

  if (isLoading) {
    return <div className="text-sm text-[var(--color-muted-fg)]">載入中…</div>
  }
  if (!job) {
    return (
      <Alert variant="destructive">
        <AlertCircle className="h-4 w-4" />
        <AlertTitle>找不到任務</AlertTitle>
        <AlertDescription>編號 {jobId} 不存在。</AlertDescription>
      </Alert>
    )
  }

  const meta = STATUS_META[job.status]
  const StatusIcon = meta.icon
  const TERMINAL: JobStatus[] = ["done", "failed", "cancelled"]
  const isRunning = !TERMINAL.includes(job.status)
  const elapsedSec = job.started_at && job.completed_at
    ? (new Date(job.completed_at).getTime() - new Date(job.started_at).getTime()) / 1000
    : null

  return (
    <div className="space-y-6">
      <CheckpointGate job={job} events={events} />
      {/* Header card */}
      <Card>
        <CardHeader>
          <div className="flex items-start justify-between gap-4">
            <div className="space-y-2 min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <Badge variant={meta.variant} className="gap-1.5">
                  <StatusIcon className={"h-3.5 w-3.5 " + (job.status === "running" ? "animate-spin" : "")} />
                  {meta.label}
                </Badge>
                <Badge variant="outline">{job.type}</Badge>
                <Badge variant="outline">{job.mode}</Badge>
                {isRunning && connected && (
                  <Badge variant="muted" className="gap-1">
                    <Radio className="h-3 w-3" /> 即時連線
                  </Badge>
                )}
              </div>
              <CardTitle className="text-xl break-words">{job.instruction}</CardTitle>
              <div className="text-xs text-[var(--color-muted-fg)] flex flex-wrap gap-x-4 gap-y-1">
                <span>建立於 {format(new Date(job.created_at), "yyyy-MM-dd HH:mm:ss")}</span>
                <span>實習生：{job.intern_name}</span>
                <span>輸出目錄：{job.subdir}</span>
                {elapsedSec !== null && <span>耗時：{elapsedSec.toFixed(1)}s</span>}
              </div>
            </div>
            <div className="text-right shrink-0">
              <div className="text-xs text-[var(--color-muted-fg)]">成本</div>
              <div className="text-lg font-semibold tabular-nums">
                ${job.cost_usd.toFixed(4)}
              </div>
            </div>
          </div>
        </CardHeader>
        {job.status === "done" && (
          <CardContent className="border-t border-[var(--color-border)] pt-4 flex flex-wrap gap-3">
            <Button onClick={handleDownload} variant="accent">
              <Download className="h-4 w-4" />
              下載 .docx
            </Button>
            <a
              href={`/api/jobs/${job.id}/log`}
              target="_blank"
              rel="noreferrer"
              className="inline-flex"
            >
              <Button variant="outline">
                <FileText className="h-4 w-4" />
                檢視 .log
              </Button>
            </a>
          </CardContent>
        )}
        {job.status === "failed" && job.error && (
          <CardContent className="border-t border-[var(--color-border)] pt-4">
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" />
              <AlertTitle>執行失敗</AlertTitle>
              <AlertDescription className="font-mono text-xs">{job.error}</AlertDescription>
            </Alert>
          </CardContent>
        )}
      </Card>

      {/* Live progress log */}
      <Card>
        <CardHeader className="border-b border-[var(--color-border)]">
          <div className="flex items-center justify-between">
            <CardTitle className="text-base">執行紀錄</CardTitle>
            <span className="text-xs text-[var(--color-muted-fg)]">
              {events.length} 個事件
            </span>
          </div>
        </CardHeader>
        <CardContent className="p-0">
          <EventLog events={events} live={isRunning} />
        </CardContent>
      </Card>
    </div>
  )
}

/** Per-event row. Picks out the interesting payload fields per kind. */
function EventLog({ events, live }: { events: JobEvent[]; live: boolean }) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    // Auto-scroll to bottom when new events arrive.
    if (ref.current) ref.current.scrollTop = ref.current.scrollHeight
  }, [events.length])

  if (events.length === 0) {
    return (
      <div className="p-8 text-center text-sm text-[var(--color-muted-fg)]">
        {live ? (
          <span className="inline-flex items-center gap-2">
            <Loader2 className="h-4 w-4 animate-spin" />
            等待事件…
          </span>
        ) : (
          "沒有事件可顯示"
        )}
      </div>
    )
  }

  return (
    <div
      ref={ref}
      className="max-h-[480px] overflow-auto font-mono text-xs leading-relaxed"
    >
      {events.map((e, idx) => (
        <div
          key={e.id ?? idx}
          className="flex items-start gap-3 px-6 py-1.5 border-b border-[var(--color-border)]/50 last:border-0 hover:bg-[var(--color-muted)]/30"
        >
          <span className="text-[var(--color-muted-fg)] tabular-nums shrink-0 w-20">
            {e.ts ? format(new Date(e.ts), "HH:mm:ss") : ""}
          </span>
          <KindBadge kind={e.kind} />
          <span className="text-[var(--color-fg)] break-all">
            {summarize(e)}
          </span>
        </div>
      ))}
    </div>
  )
}

function KindBadge({ kind }: { kind: string }) {
  const tone =
    kind === "job_completed" ? "success" :
    kind === "job_failed" || kind === "error" ? "destructive" :
    kind === "warning" ? "warning" :
    kind === "search_query" || kind === "search_batch" ? "default" :
    kind === "evaluate" ? "accent" :
    "muted"
  return <Badge variant={tone} className="shrink-0 font-mono text-[10px]">{kind}</Badge>
}

/** Render a one-line summary of the payload. */
function summarize(e: JobEvent): string {
  const p = e.payload
  switch (e.kind) {
    case "job_started":
      return "任務啟動"
    case "job_completed":
      return `任務完成 · cost=$${(p.cost_usd as number | undefined)?.toFixed(4) ?? "?"}`
    case "job_failed":
      return `失敗：${String(p.error ?? "未知錯誤")}`
    case "node_start":
      return `進入節點：${String(p.node ?? "?")}` +
             (p.round !== undefined ? ` (round=${String(p.round)})` : "") +
             (p.mode ? ` mode=${String(p.mode)}` : "")
    case "node_end":
      return `節點結束：${String(p.node ?? "?")}` +
             (p.output_path ? ` → ${String(p.output_path).split("/").pop()}` : "")
    case "search_batch":
      return `初始搜尋批次：${String(p.n_queries ?? "?")} 條查詢`
    case "search_query":
      return `搜尋：${String(p.query ?? "")}` +
             (p.n_results !== undefined ? ` (${String(p.n_results)} 筆結果)` : "")
    case "evaluate":
      return `評估：done=${p.done ?? 0} pending=${p.pending ?? 0} unresolved=${p.unresolved ?? 0}` +
             (p.round !== undefined ? ` (round=${String(p.round)})` : "")
    case "confirm_tasks_request":
      return `等待任務確認（${(p.payload as { tasks?: unknown[] } | undefined)?.tasks?.length ?? 0} 條）`
    case "subject_review_request": {
      const n = (p.payload as { mentions?: unknown[] } | undefined)?.mentions?.length ?? 0
      return `等待 STT 校稿（${n} 個主體）`
    }
    case "slide_confirm_request": {
      const n = (p.payload as { slides_plan?: unknown[] } | undefined)?.slides_plan?.length ?? 0
      return `等待投影片確認（${n} 張）`
    }
    case "confirm_tasks_resolved":
    case "subject_review_resolved":
    case "slide_confirm_resolved":
      return `已${p.reason === "cancelled" ? "取消" : p.reason === "timeout" ? "逾時" : "確認"}（耗時 ${(p.elapsed as number | undefined)?.toFixed(1) ?? "?"}s）`
    case "job_cancelled":
      return "任務已取消"
    default: {
      // Fallback: stringify whatever's there minus the noisy fields.
      const { kind: _k, ts: _t, _event_id: _i, ...rest } = p
      return Object.keys(rest).length === 0 ? "" : JSON.stringify(rest)
    }
  }
}
