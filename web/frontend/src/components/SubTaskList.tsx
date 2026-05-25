/**
 * SubTaskList — renders the N sub-task cards of an stt_pipeline parent.
 *
 * Shown only when the parent's type === "stt_pipeline". Each card
 * exposes:
 *   - label + agent_type chip
 *   - per-sub-task status badge
 *   - cost
 *   - download button (when done) + log link
 */
import { api, type JobSubTaskResponse, type JobStatus } from "@/api/client"
import { useJobSubtasks } from "@/api/hooks"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import {
  CheckCircle2, Clock, Download, FileText, Loader2,
  PauseCircle, XCircle,
} from "lucide-react"

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

interface Props {
  parentId: string
  enabled: boolean   // only render when parent.type === "stt_pipeline"
}

export function SubTaskList({ parentId, enabled }: Props) {
  const { data: subtasks = [], isLoading } = useJobSubtasks(parentId, enabled)
  if (!enabled) return null

  return (
    <Card>
      <CardHeader className="border-b border-[var(--color-border)]">
        <div className="flex items-center justify-between">
          <CardTitle className="text-base">子任務</CardTitle>
          <span className="text-xs text-[var(--color-muted-fg)]">
            {subtasks.length} 條
          </span>
        </div>
      </CardHeader>
      <CardContent className="p-0">
        {isLoading && subtasks.length === 0 && (
          <div className="p-6 text-sm text-[var(--color-muted-fg)] text-center">
            載入中…
          </div>
        )}
        {!isLoading && subtasks.length === 0 && (
          <div className="p-6 text-sm text-[var(--color-muted-fg)] text-center">
            尚未產生子任務（等待 STT → planner 解析）
          </div>
        )}
        <div className="divide-y divide-[var(--color-border)]">
          {subtasks.map((s) => <SubTaskRow key={s.id} sub={s} />)}
        </div>
      </CardContent>
    </Card>
  )
}

function SubTaskRow({ sub }: { sub: JobSubTaskResponse }) {
  const meta = STATUS_META[sub.status]
  const StatusIcon = meta.icon

  const handleDownload = async () => {
    const { blob, filename } = await api.downloadSubtask(sub.id)
    const url = URL.createObjectURL(blob)
    const a = document.createElement("a")
    a.href = url
    a.download = filename
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="px-6 py-4 flex items-start gap-4">
      <Badge variant="outline" className="mt-0.5 shrink-0">{sub.idx + 1}</Badge>

      <div className="flex-1 min-w-0 space-y-1">
        <div className="flex items-center gap-2 flex-wrap">
          <Badge variant={meta.variant} className="gap-1.5">
            <StatusIcon className={"h-3 w-3 " + (sub.status === "running" ? "animate-spin" : "")} />
            {meta.label}
          </Badge>
          <Badge variant="outline">{sub.agent_type}</Badge>
        </div>
        <div className="text-sm font-medium break-words">{sub.label}</div>
        <div className="text-xs text-[var(--color-muted-fg)] line-clamp-2">{sub.instruction}</div>
        {sub.error && (
          <div className="text-xs font-mono text-[var(--color-destructive)] mt-1">{sub.error}</div>
        )}
      </div>

      <div className="text-right shrink-0 space-y-2">
        <div>
          <div className="text-xs text-[var(--color-muted-fg)]">成本</div>
          <div className="font-mono text-sm tabular-nums">${sub.cost_usd.toFixed(4)}</div>
        </div>
        {sub.status === "done" && sub.output_path && (
          <div className="flex flex-col gap-1.5 items-end">
            <Button onClick={handleDownload} size="sm" variant="outline">
              <Download className="h-3 w-3" />
              下載
            </Button>
            <a
              href={`/api/jobs/subtasks/${sub.id}/log`}
              target="_blank"
              rel="noreferrer"
              className="text-[10px] text-[var(--color-muted-fg)] hover:underline inline-flex items-center gap-1"
            >
              <FileText className="h-2.5 w-2.5" />
              .log
            </a>
          </div>
        )}
      </div>
    </div>
  )
}
