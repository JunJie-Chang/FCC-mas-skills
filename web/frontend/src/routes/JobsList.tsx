/**
 * /jobs — paginated history with filters + search.
 *
 * Filter chips (type / status / intern) at the top + a debounced
 * search input that runs LIKE on instruction. Row click goes to
 * /jobs/$jobId. Sub-tasks aren't listed flat — they live on the
 * parent's detail page so cost doesn't double-count.
 */
import { useEffect, useMemo, useState } from "react"
import { Link } from "@tanstack/react-router"
import { format } from "date-fns"
import { useJobList, type JobListFilters } from "@/api/hooks"
import type { JobResponse, JobStatus } from "@/api/client"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  CheckCircle2, ChevronLeft, ChevronRight, Clock, Loader2,
  PauseCircle, Search, X, XCircle,
} from "lucide-react"
import { cn } from "@/lib/utils"

const PAGE_SIZE = 25

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

const TYPE_LABELS: Record<string, string> = {
  company_info:   "公司研究",
  person_info:    "人物背景",
  podcast:        "Podcast",
  translation:    "翻譯",
  meeting:        "會議紀錄",
  letter:         "公函",
  verbal_cleanup: "口述清稿",
  speech_ppt:     "演講 PPT",
  stt_pipeline:   "口述任務",
}

const TYPE_FILTERS: { value: string; label: string }[] = [
  { value: "",              label: "全部類型" },
  { value: "company_info",  label: TYPE_LABELS.company_info! },
  { value: "stt_pipeline",  label: TYPE_LABELS.stt_pipeline! },
  { value: "person_info",   label: TYPE_LABELS.person_info! },
  { value: "podcast",       label: TYPE_LABELS.podcast! },
  { value: "speech_ppt",    label: TYPE_LABELS.speech_ppt! },
  { value: "translation",   label: TYPE_LABELS.translation! },
  { value: "meeting",       label: TYPE_LABELS.meeting! },
  { value: "verbal_cleanup",label: TYPE_LABELS.verbal_cleanup! },
]

const STATUS_FILTERS: { value: string; label: string }[] = [
  { value: "",          label: "全部狀態" },
  { value: "done",      label: "完成" },
  { value: "running",   label: "執行中" },
  { value: "failed",    label: "失敗" },
  { value: "cancelled", label: "已取消" },
]

/** Translation jobs store JSON in instruction; show title only. */
function previewInstruction(job: JobResponse, max = 80): string {
  let text = job.instruction || ""
  if (job.type === "translation") {
    try {
      const parsed = JSON.parse(text) as { title?: string }
      if (parsed.title) text = parsed.title
    } catch { /* fall through */ }
  }
  return text.length > max ? text.slice(0, max) + "…" : text
}

export function JobsListPage() {
  // Filter state — kept local; query is built from these and passed
  // to useJobList. Debounce the search box so we don't refetch on
  // every keystroke.
  const [typeFilter, setTypeFilter]     = useState("")
  const [statusFilter, setStatusFilter] = useState("")
  const [searchInput, setSearchInput]   = useState("")
  const [search, setSearch]             = useState("")
  const [page, setPage]                 = useState(0)

  useEffect(() => {
    const t = setTimeout(() => { setSearch(searchInput); setPage(0) }, 300)
    return () => clearTimeout(t)
  }, [searchInput])

  // Reset page on filter change.
  useEffect(() => { setPage(0) }, [typeFilter, statusFilter])

  const filters: JobListFilters = useMemo(() => ({
    limit:  PAGE_SIZE,
    offset: page * PAGE_SIZE,
    ...(typeFilter   ? { type:   typeFilter   } : {}),
    ...(statusFilter ? { status: statusFilter } : {}),
    ...(search       ? { search                  } : {}),
  }), [page, typeFilter, statusFilter, search])

  const { data, isLoading, isFetching } = useJobList(filters)
  const jobs = data?.jobs ?? []
  const total = data?.total ?? 0
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))

  const anyFilter = typeFilter || statusFilter || search
  const clearAll = () => {
    setTypeFilter("")
    setStatusFilter("")
    setSearchInput("")
    setSearch("")
    setPage(0)
  }

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">任務歷史</h1>
          <p className="text-sm text-[var(--color-muted-fg)] mt-1">
            共 {total} 筆。點擊任一列查看細節 / 下載輸出。
          </p>
        </div>
        {anyFilter && (
          <Button variant="ghost" size="sm" onClick={clearAll}>
            <X className="h-3.5 w-3.5" />
            清除篩選
          </Button>
        )}
      </div>

      {/* Filter row */}
      <Card>
        <CardContent className="space-y-3 p-4">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-[var(--color-muted-fg)]" />
            <Input
              placeholder="搜尋指令文字…（公司名、人名、關鍵字）"
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              className="pl-9"
            />
          </div>

          <div className="flex flex-wrap gap-x-6 gap-y-2">
            <FilterChipGroup
              label="類型"
              options={TYPE_FILTERS}
              value={typeFilter}
              onChange={setTypeFilter}
            />
            <FilterChipGroup
              label="狀態"
              options={STATUS_FILTERS}
              value={statusFilter}
              onChange={setStatusFilter}
            />
          </div>
        </CardContent>
      </Card>

      {/* List */}
      <Card>
        <CardHeader className="border-b border-[var(--color-border)] flex flex-row items-center justify-between">
          <CardTitle className="text-base">
            {isFetching && <Loader2 className="h-3.5 w-3.5 animate-spin inline-block mr-1.5" />}
            結果（{total}）
          </CardTitle>
          <CardDescription className="text-xs">
            第 {page + 1} / {totalPages} 頁
          </CardDescription>
        </CardHeader>
        <CardContent className="p-0">
          {isLoading && jobs.length === 0 && (
            <div className="p-8 text-center text-sm text-[var(--color-muted-fg)]">載入中…</div>
          )}
          {!isLoading && jobs.length === 0 && (
            <div className="p-8 text-center text-sm text-[var(--color-muted-fg)]">
              沒有符合的任務{anyFilter ? "（換個篩選試試）" : ""}
            </div>
          )}
          <div className="divide-y divide-[var(--color-border)]">
            {jobs.map((j) => <JobRow key={j.id} job={j} />)}
          </div>
        </CardContent>
        {totalPages > 1 && (
          <div className="border-t border-[var(--color-border)] px-6 py-3 flex items-center justify-between text-sm">
            <span className="text-[var(--color-muted-fg)]">
              {page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, total)} / {total}
            </span>
            <div className="flex gap-2">
              <Button
                variant="outline" size="sm"
                disabled={page === 0} onClick={() => setPage((p) => Math.max(0, p - 1))}
              >
                <ChevronLeft className="h-3.5 w-3.5" />
                上一頁
              </Button>
              <Button
                variant="outline" size="sm"
                disabled={page >= totalPages - 1} onClick={() => setPage((p) => p + 1)}
              >
                下一頁
                <ChevronRight className="h-3.5 w-3.5" />
              </Button>
            </div>
          </div>
        )}
      </Card>
    </div>
  )
}

function FilterChipGroup({
  label, options, value, onChange,
}: {
  label: string
  options: { value: string; label: string }[]
  value: string
  onChange: (v: string) => void
}) {
  return (
    <div className="flex items-center gap-2 flex-wrap">
      <span className="text-xs text-[var(--color-muted-fg)] shrink-0">{label}：</span>
      {options.map((opt) => (
        <button
          key={opt.value || "_all"}
          type="button"
          onClick={() => onChange(opt.value)}
          className={cn(
            "px-2.5 py-1 rounded-full text-xs border transition-colors",
            value === opt.value
              ? "border-[var(--color-accent)] bg-[var(--color-accent)]/10 text-[var(--color-fg)] font-medium"
              : "border-[var(--color-border)] text-[var(--color-muted-fg)] hover:bg-[var(--color-muted)]"
          )}
        >
          {opt.label}
        </button>
      ))}
    </div>
  )
}

function JobRow({ job }: { job: JobResponse }) {
  const meta = STATUS_META[job.status]
  const StatusIcon = meta.icon
  const typeLabel = TYPE_LABELS[job.type] ?? job.type

  return (
    <Link
      to="/jobs/$jobId"
      params={{ jobId: job.id }}
      className="block px-6 py-3 hover:bg-[var(--color-muted)]/40 transition-colors"
    >
      <div className="flex items-start gap-4">
        <div className="flex-1 min-w-0 space-y-1">
          <div className="flex items-center gap-2 flex-wrap">
            <Badge variant={meta.variant} className="gap-1">
              <StatusIcon className={"h-3 w-3 " + (job.status === "running" ? "animate-spin" : "")} />
              {meta.label}
            </Badge>
            <Badge variant="outline">{typeLabel}</Badge>
            <span className="text-xs text-[var(--color-muted-fg)] tabular-nums">
              {format(new Date(job.created_at), "MM-dd HH:mm")}
            </span>
            <span className="text-xs text-[var(--color-muted-fg)]">· {job.intern_name}</span>
          </div>
          <div className="text-sm break-words">{previewInstruction(job)}</div>
        </div>
        <div className="text-right shrink-0 text-sm tabular-nums">
          ${job.cost_usd.toFixed(4)}
        </div>
      </div>
    </Link>
  )
}
