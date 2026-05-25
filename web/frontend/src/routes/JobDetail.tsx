import { useParams } from "@tanstack/react-router"
import { useEffect, useRef, useState } from "react"
import { format } from "date-fns"
import { useJob, useInvalidateJob } from "@/api/hooks"
import { useJobEvents, type JobEvent } from "@/api/useJobEvents"
import { api, type JobStatus } from "@/api/client"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { CheckpointGate } from "@/components/checkpoints/CheckpointGate"
import { SubTaskList } from "@/components/SubTaskList"
import { useQueryClient } from "@tanstack/react-query"
import {
  AlertCircle, Ban, CheckCircle2, Clock, Download, FileText, Loader2,
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
  const qc = useQueryClient()

  // When the SSE stream sends a terminal event, refetch the job row so
  // status / cost / output_path reflect the final state.
  useEffect(() => {
    if (terminal && jobId) invalidate(jobId)
  }, [terminal, jobId, invalidate])

  // Sub-task progress events should refresh the sub-task list cache
  // (TanStack Query won't know to refetch otherwise — and 10s polling
  // would feel laggy when the user is watching live).
  useEffect(() => {
    if (!jobId || events.length === 0) return
    const last = events[events.length - 1]
    if (
      last &&
      (last.kind === "subtask_started" ||
       last.kind === "subtask_completed" ||
       last.kind === "subtasks_planned")
    ) {
      qc.invalidateQueries({ queryKey: ["jobs", jobId, "subtasks"] })
    }
  }, [events.length, jobId, qc, events])

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

  const [cancelling, setCancelling] = useState(false)
  const handleCancel = async () => {
    if (!jobId) return
    if (!window.confirm("確定取消這個任務？已產出的成本不會退款，但會立即停止後續執行。")) return
    setCancelling(true)
    try {
      await api.cancelJob(jobId)
      invalidate(jobId)
    } catch (e) {
      window.alert(e instanceof Error ? e.message : String(e))
    } finally {
      setCancelling(false)
    }
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

  // Translation stores its structured payload as a JSON-encoded
  // instruction (router unpacks it server-side). Don't dump the raw
  // JSON in the title — show the actual article title + source.
  const { title, subtitle } = displayHeading(job.type, job.instruction)

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
              <CardTitle className="text-xl break-words">{title}</CardTitle>
              {subtitle && (
                <div className="text-sm text-[var(--color-muted-fg)] break-words">
                  {subtitle}
                </div>
              )}
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
        {/* Cancel button — only while a non-terminal status (queued /
            running / needs_*) lets the user pull the plug if the agent
            went off the rails. Soft cancel: backend resolves any open
            checkpoint future + sets status=CANCELLED; an actively
            running node finishes the call it's mid-flight on. */}
        {!TERMINAL.includes(job.status) && (
          <CardContent className="border-t border-[var(--color-border)] pt-4 flex flex-wrap gap-3">
            <Button
              variant="outline"
              onClick={handleCancel}
              disabled={cancelling}
              className="border-[var(--color-destructive)]/40 text-[var(--color-destructive)] hover:bg-[var(--color-destructive)]/10"
            >
              {cancelling ? (
                <><Loader2 className="h-4 w-4 animate-spin" /> 取消中…</>
              ) : (
                <><Ban className="h-4 w-4" /> 取消任務</>
              )}
            </Button>
            <span className="text-xs text-[var(--color-muted-fg)] self-center">
              已產出的成本 (${job.cost_usd.toFixed(4)}) 不會退款；節點執行中可能會跑完當前一步才停。
            </span>
          </CardContent>
        )}
        {/* Parent download / log only when the parent itself has a file.
            stt_pipeline parents return output_path="" — their deliverables
            live on the sub-task cards, so the parent's action bar would
            point nowhere. Single-agent jobs always have output_path set
            on success. */}
        {job.status === "done" && job.output_path && (
          <CardContent className="border-t border-[var(--color-border)] pt-4 flex flex-wrap gap-3">
            <Button onClick={handleDownload} variant="accent">
              <Download className="h-4 w-4" />
              下載 .docx
            </Button>
            {job.log_path && (
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
            )}
          </CardContent>
        )}
        {job.status === "failed" && job.error && (
          <CardContent className="border-t border-[var(--color-border)] pt-4">
            <FailureAlert error={job.error} />
          </CardContent>
        )}
      </Card>

      {/* Sub-tasks (only for stt_pipeline jobs — component handles
          its own "no-op when not enabled" rendering) */}
      <SubTaskList parentId={job.id} enabled={job.type === "stt_pipeline"} />

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
    case "stt_started":
      return "STT 轉錄開始"
    case "stt_completed":
      return `STT 完成（${String(p.n_chars ?? "?")} 字）`
    case "subtasks_planned":
      return `規劃完成：${String(p.n ?? "?")} 個子任務`
    case "subtask_started":
      return `子任務 ${String((p.subtask_idx as number ?? 0) + 1)} 開始：[${String(p.agent_type ?? "?")}] ${String(p.label ?? "")}`
    case "subtask_completed":
      return `子任務 ${String((p.subtask_idx as number ?? 0) + 1)} ${p.status === "done" ? "完成" : p.status === "cancelled" ? "已取消" : "失敗"} · cost=$${(p.cost_usd as number | undefined)?.toFixed(4) ?? "?"}` +
             (p.error ? ` · ${String(p.error)}` : "")
    default: {
      // Fallback: stringify whatever's there minus the noisy fields.
      const { kind: _k, ts: _t, _event_id: _i, ...rest } = p
      return Object.keys(rest).length === 0 ? "" : JSON.stringify(rest)
    }
  }
}

/**
 * Per-type header text. Most agent types store a plain-text instruction
 * we can show directly; translation stores a JSON envelope that needs
 * unpacking so the user sees the actual article title rather than the
 * literal {"title":"...","source":"..."} string.
 *
 * Returns { title, subtitle? } — title goes in the big heading,
 * subtitle (when present) appears just below it in muted text.
 */
function displayHeading(
  jobType: string,
  instruction: string,
): { title: string; subtitle?: string } {
  if (jobType === "translation") {
    try {
      const parsed = JSON.parse(instruction) as {
        title?: string
        source?: string
        pub_date?: string
      }
      if (parsed && typeof parsed.title === "string") {
        const subBits: string[] = []
        if (parsed.source) subBits.push(parsed.source)
        if (parsed.pub_date) subBits.push(parsed.pub_date)
        return {
          title:    parsed.title,
          subtitle: subBits.length > 0 ? subBits.join(" · ") : undefined,
        }
      }
    } catch {
      /* fall through to raw display */
    }
  }
  return { title: instruction || "(無指令)" }
}

/**
 * Friendly failure renderer. Most agent failures are one of a small
 * set of patterns (Tavily quota, Anthropic rate limit, STT format,
 * upload missing). Pattern-match on the error string and surface a
 * hint alongside the raw message so the operator knows where to
 * start. Raw message stays visible — never hidden.
 */
function FailureAlert({ error }: { error: string }) {
  const hint = ((): string | null => {
    const e = error.toLowerCase()
    if (e.includes("rate") && (e.includes("limit") || e.includes("429"))) {
      return "Anthropic / Tavily 速率限制。等 1–2 分鐘再重新送出；或檢查 .env 是否還在 free tier 額度內。"
    }
    if (e.includes("stt") && (e.includes("不支援") || e.includes("unsupported"))) {
      return "音檔格式 OpenAI 不認。請從 /new-audio 重新上傳 m4a / mp3 / mp4 / wav / webm。"
    }
    if (e.includes("找不到上傳") || e.includes("filenotfound") || e.includes("no such file")) {
      return "上傳檔案在伺服器上找不到（可能被清掉或路徑改變）。請重新上傳。"
    }
    if (e.includes("ticker") && e.includes("not found")) {
      return "Ticker 解析失敗 — 任務指令可能拼錯公司名，或公司未上市。"
    }
    if (e.includes("badrequest") || e.includes("400")) {
      return "上游 API 拒絕請求。多半是 prompt 過長或格式不對；看 .log 詳情。"
    }
    if (e.includes("timeout") || e.includes("timed out")) {
      return "操作逾時。可能是網路或上游 API 慢；直接重試。"
    }
    return null
  })()

  return (
    <Alert variant="destructive">
      <AlertCircle className="h-4 w-4" />
      <AlertTitle>執行失敗</AlertTitle>
      <AlertDescription className="space-y-2">
        <div className="font-mono text-xs break-all whitespace-pre-wrap">{error}</div>
        {hint && (
          <div className="text-xs">
            <span className="font-semibold">可能原因：</span>
            {hint}
          </div>
        )}
      </AlertDescription>
    </Alert>
  )
}
