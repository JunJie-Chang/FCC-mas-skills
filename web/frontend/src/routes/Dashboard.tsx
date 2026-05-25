/**
 * / — Dashboard. Surface what an FCC intern actually needs at a glance:
 *   - This-month spend (the partner asks)
 *   - Status breakdown of recent jobs
 *   - Cost by agent type (where did the money go)
 *   - 5 most recent jobs (click to detail)
 *   - CTA grid: jump straight to whichever input flow they want
 *
 * Recharts deliberately not pulled in for v1 — a 30-day trend bar
 * doesn't beat the spend-by-type breakdown for daily use, and we keep
 * the bundle slim. Cost trend data is in /stats/summary already, easy
 * to add later if asked.
 */
import { Link } from "@tanstack/react-router"
import { format } from "date-fns"
import { useStatsSummary } from "@/api/hooks"
import type { JobResponse, JobStatus } from "@/api/client"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import {
  CheckCircle2, Clock, FilePlus2, Headphones, Languages, Loader2,
  Mic, PauseCircle, Presentation, XCircle,
} from "lucide-react"
import { cn } from "@/lib/utils"

const STATUS_LABELS: Record<JobStatus, string> = {
  queued:               "排隊中",
  running:              "執行中",
  needs_confirm:        "等待確認",
  needs_subject_review: "校稿中",
  needs_slide_confirm:  "確認投影片",
  done:                 "完成",
  failed:               "失敗",
  cancelled:            "已取消",
}
const STATUS_ICON: Record<JobStatus, React.ComponentType<{ className?: string }>> = {
  queued: Clock, running: Loader2,
  needs_confirm: PauseCircle, needs_subject_review: PauseCircle, needs_slide_confirm: PauseCircle,
  done: CheckCircle2, failed: XCircle, cancelled: XCircle,
}
const STATUS_VARIANT: Record<JobStatus, "muted" | "success" | "destructive" | "warning"> = {
  queued: "muted", running: "warning",
  needs_confirm: "warning", needs_subject_review: "warning", needs_slide_confirm: "warning",
  done: "success", failed: "destructive", cancelled: "muted",
}

const TYPE_LABELS: Record<string, string> = {
  company_info: "公司研究", person_info: "人物背景",
  podcast: "Podcast", translation: "翻譯",
  meeting: "會議紀錄", letter: "公函",
  verbal_cleanup: "口述清稿", speech_ppt: "演講 PPT",
  stt_pipeline: "口述任務",
}

interface CTA {
  href: string
  label: string
  description: string
  icon: React.ComponentType<{ className?: string }>
}

const CTAS: CTA[] = [
  { href: "/new",             label: "新增任務",       description: "公司研究 / 人物 / 會議 / 口述清稿",   icon: FilePlus2 },
  { href: "/new-audio",       label: "口述任務 (STT)", description: "音檔 → 自動轉錄 → 多任務 fan-out",  icon: Mic },
  { href: "/new-podcast",     label: "Podcast 任務",   description: "主題 + N 題研究",                   icon: Headphones },
  { href: "/new-speech-ppt",  label: "演講 PPT 任務",  description: "投影片結構 + DALL-E 圖",            icon: Presentation },
  { href: "/new-translation", label: "翻譯任務",       description: "外文文章中譯",                       icon: Languages },
]

export function DashboardPage() {
  const { data: stats, isLoading } = useStatsSummary(30)

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">儀表板</h1>
        <p className="text-sm text-[var(--color-muted-fg)] mt-1">
          {stats ? `近 ${stats.window_days} 天概況` : "載入中…"}
        </p>
      </div>

      {/* Stat strip */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <Card>
          <CardContent className="p-4">
            <div className="text-xs text-[var(--color-muted-fg)]">近 30 天總成本</div>
            <div className="text-3xl font-semibold tabular-nums mt-1">
              ${stats?.total_cost_usd.toFixed(2) ?? "—"}
            </div>
            <div className="text-xs text-[var(--color-muted-fg)] mt-1">
              {stats?.job_count ?? "—"} 個任務
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-4">
            <div className="text-xs text-[var(--color-muted-fg)] mb-2">狀態分布</div>
            {(stats?.counts_by_status ?? []).map((s) => {
              const Icon = STATUS_ICON[s.status as JobStatus]
              return (
                <div key={s.status} className="flex items-center justify-between text-sm py-0.5">
                  <span className="flex items-center gap-1.5 text-[var(--color-muted-fg)]">
                    <Icon className="h-3 w-3" />
                    {STATUS_LABELS[s.status as JobStatus]}
                  </span>
                  <span className="tabular-nums">{s.count}</span>
                </div>
              )
            })}
            {!stats && <div className="text-sm text-[var(--color-muted-fg)]">—</div>}
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-4">
            <div className="text-xs text-[var(--color-muted-fg)] mb-2">類型成本</div>
            {(stats?.cost_by_type ?? []).slice(0, 5).map((row) => (
              <div key={row.type} className="text-sm py-0.5 flex items-center justify-between">
                <span className="text-[var(--color-muted-fg)] truncate">
                  {TYPE_LABELS[row.type] ?? row.type}
                </span>
                <span className="tabular-nums">
                  ${row.cost_usd.toFixed(2)}{" "}
                  <span className="text-xs text-[var(--color-muted-fg)]">({row.count})</span>
                </span>
              </div>
            ))}
            {stats && stats.cost_by_type.length === 0 && (
              <div className="text-sm text-[var(--color-muted-fg)]">沒有資料</div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Quick actions */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">開始新任務</CardTitle>
          <CardDescription>選擇對應的入口；每種任務有自己最適合的表單。</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {CTAS.map((c) => (
              <Link
                key={c.href}
                to={c.href}
                className={cn(
                  "group rounded-lg border border-[var(--color-border)] p-4 transition-colors",
                  "hover:border-[var(--color-accent)] hover:bg-[var(--color-accent)]/5",
                )}
              >
                <div className="flex items-center gap-2 mb-1">
                  <c.icon className="h-4 w-4 text-[var(--color-accent)]" />
                  <span className="font-medium text-sm">{c.label}</span>
                </div>
                <p className="text-xs text-[var(--color-muted-fg)]">{c.description}</p>
              </Link>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Recent jobs */}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between border-b border-[var(--color-border)]">
          <CardTitle className="text-base">最近任務</CardTitle>
          <Link to="/jobs" className="text-xs text-[var(--color-muted-fg)] hover:underline">
            檢視全部 →
          </Link>
        </CardHeader>
        <CardContent className="p-0">
          {isLoading && (
            <div className="p-6 text-center text-sm text-[var(--color-muted-fg)]">載入中…</div>
          )}
          {!isLoading && (stats?.recent_jobs ?? []).length === 0 && (
            <div className="p-6 text-center text-sm text-[var(--color-muted-fg)]">
              沒有任務紀錄 — 從上方「開始新任務」開始吧。
            </div>
          )}
          <div className="divide-y divide-[var(--color-border)]">
            {(stats?.recent_jobs ?? []).map((j) => <RecentJobRow key={j.id} job={j} />)}
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

function RecentJobRow({ job }: { job: JobResponse }) {
  const Icon = STATUS_ICON[job.status]
  const typeLabel = TYPE_LABELS[job.type] ?? job.type
  // Same translation-JSON unpack as JobsList — keep consistent.
  let text = job.instruction || ""
  if (job.type === "translation") {
    try {
      const p = JSON.parse(text) as { title?: string }
      if (p.title) text = p.title
    } catch { /* keep raw */ }
  }
  return (
    <Link
      to="/jobs/$jobId"
      params={{ jobId: job.id }}
      className="block px-6 py-3 hover:bg-[var(--color-muted)]/40 transition-colors"
    >
      <div className="flex items-center gap-3">
        <Badge variant={STATUS_VARIANT[job.status]} className="gap-1 shrink-0">
          <Icon className={"h-3 w-3 " + (job.status === "running" ? "animate-spin" : "")} />
          {STATUS_LABELS[job.status]}
        </Badge>
        <Badge variant="outline" className="shrink-0">{typeLabel}</Badge>
        <span className="text-sm flex-1 truncate">{text}</span>
        <span className="text-xs text-[var(--color-muted-fg)] tabular-nums shrink-0">
          {format(new Date(job.created_at), "MM-dd HH:mm")}
        </span>
        <span className="text-sm tabular-nums shrink-0">${job.cost_usd.toFixed(4)}</span>
      </div>
    </Link>
  )
}
