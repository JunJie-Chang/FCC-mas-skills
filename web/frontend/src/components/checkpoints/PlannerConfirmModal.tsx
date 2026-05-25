/**
 * PlannerConfirmModal — agent paused at planner.confirm.
 *
 * Browser mirror of the CLI's `m / d / a / [N] / y / n` controls,
 * built on a list of {agent_type, label, instruction}. The user can
 * edit any task inline, delete unwanted rows, add fresh ones, or
 * cancel the whole batch. Merge (CLI's `m a,b`) is left to the
 * follow-up phase — it needs a backend Haiku merge call that the web
 * route currently doesn't expose.
 *
 * Submits to POST /jobs/{id}/confirm with one of:
 *   {"action": "confirm", "tasks": [...]}
 *   {"action": "cancel"}
 */
import { useEffect, useState } from "react"
import {
  Dialog, DialogBody, DialogContent, DialogDescription, DialogFooter,
  DialogHeader, DialogTitle,
} from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Textarea } from "@/components/ui/textarea"
import { Trash2, Plus, AlertTriangle } from "lucide-react"
import type { AgentType } from "@/api/client"

export interface PlanTaskDraft {
  agent_type: AgentType
  label: string
  instruction: string
}

interface Props {
  open: boolean
  initialTasks: PlanTaskDraft[]
  submitting: boolean
  onConfirm: (tasks: PlanTaskDraft[]) => void
  onCancel: () => void
}

const AGENT_TYPE_LABELS: Record<AgentType, string> = {
  company_info:   "公司研究",
  person_info:    "人物背景",
  translation:    "翻譯",
  letter:         "公函",
  meeting:        "會議紀錄",
  verbal_cleanup: "口述清稿",
  podcast:        "Podcast",
  speech_ppt:     "演講 PPT",
}

export function PlannerConfirmModal({
  open, initialTasks, submitting, onConfirm, onCancel,
}: Props) {
  const [tasks, setTasks] = useState<PlanTaskDraft[]>(initialTasks)

  // Reset to the latest payload whenever a fresh checkpoint opens.
  useEffect(() => {
    setTasks(initialTasks)
  }, [initialTasks])

  const update = (idx: number, patch: Partial<PlanTaskDraft>) => {
    setTasks((curr) => curr.map((t, i) => (i === idx ? { ...t, ...patch } : t)))
  }
  const remove = (idx: number) => {
    setTasks((curr) => curr.filter((_, i) => i !== idx))
  }
  const add = () => {
    setTasks((curr) => [
      ...curr,
      { agent_type: "company_info", label: "新任務", instruction: "" },
    ])
  }

  const valid = tasks.length > 0 && tasks.every((t) => t.instruction.trim().length > 0)

  return (
    <Dialog open={open}>
      <DialogContent size="xl">
        <DialogHeader>
          <DialogTitle>確認任務清單</DialogTitle>
          <DialogDescription>
            Agent 已將指令解析成下列任務。可以修改、刪除、新增；確認後依序執行。
          </DialogDescription>
        </DialogHeader>

        <DialogBody className="space-y-3">
          {tasks.length === 0 && (
            <div className="rounded-md border border-dashed border-[var(--color-border)] p-6 text-center text-sm text-[var(--color-muted-fg)]">
              <AlertTriangle className="mx-auto mb-2 h-5 w-5" />
              沒有任務 — 新增至少一條或取消。
            </div>
          )}

          {tasks.map((t, idx) => (
            <div
              key={idx}
              className="rounded-md border border-[var(--color-border)] p-3 space-y-2"
            >
              <div className="flex items-center gap-2">
                <Badge variant="outline">{idx + 1}</Badge>
                <select
                  value={t.agent_type}
                  onChange={(e) => update(idx, { agent_type: e.target.value as AgentType })}
                  className="h-7 rounded-md border border-[var(--color-input)] bg-[var(--color-bg)] px-2 text-xs"
                >
                  {(Object.keys(AGENT_TYPE_LABELS) as AgentType[]).map((at) => (
                    <option key={at} value={at}>
                      {AGENT_TYPE_LABELS[at]}（{at}）
                    </option>
                  ))}
                </select>
                <input
                  type="text"
                  value={t.label}
                  onChange={(e) => update(idx, { label: e.target.value })}
                  className="flex-1 h-7 rounded-md border border-[var(--color-input)] bg-[var(--color-bg)] px-2 text-xs"
                  placeholder="任務標籤"
                />
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={() => remove(idx)}
                  aria-label="刪除"
                  className="h-7 w-7"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>
              </div>
              <Textarea
                value={t.instruction}
                onChange={(e) => update(idx, { instruction: e.target.value })}
                placeholder="完整指令…"
                className="min-h-[60px] text-xs"
              />
            </div>
          ))}

          <Button variant="outline" size="sm" onClick={add} className="w-full">
            <Plus className="h-3.5 w-3.5" />
            新增任務
          </Button>
        </DialogBody>

        <DialogFooter>
          <Button variant="ghost" onClick={onCancel} disabled={submitting}>
            取消批次
          </Button>
          <Button
            variant="accent"
            disabled={!valid || submitting}
            onClick={() => onConfirm(tasks)}
          >
            {submitting ? "送出中…" : `確認執行 (${tasks.length})`}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
