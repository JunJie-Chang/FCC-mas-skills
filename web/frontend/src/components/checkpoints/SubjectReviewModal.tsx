/**
 * SubjectReviewModal — agent paused at subject_review.
 *
 * Shows the proper-noun mentions extracted from a Whisper / GPT-4o
 * transcript and lets the user correct any STT mishears before the
 * transcript is handed to the planner. Each row has:
 *   - the detected token
 *   - a "suspect" badge when Haiku flagged it
 *   - the surrounding context for jog memory
 *   - an inline replacement field
 *
 * On confirm we replace_all across the transcript and POST the result.
 * Cancel = skip review (returns the original transcript).
 */
import { useEffect, useState } from "react"
import {
  Dialog, DialogBody, DialogContent, DialogDescription, DialogFooter,
  DialogHeader, DialogTitle,
} from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { AlertTriangle, CheckCircle2 } from "lucide-react"

export interface SubjectMention {
  name: string
  context: string
  suspect: boolean
}

interface Props {
  open: boolean
  initialTranscript: string
  initialMentions: SubjectMention[]
  submitting: boolean
  onConfirm: (transcript: string) => void
  onCancel: () => void
}

export function SubjectReviewModal({
  open, initialTranscript, initialMentions, submitting, onConfirm, onCancel,
}: Props) {
  // `replacements[i]` is the user's desired text for mention `i`.
  // Empty string means "keep original".
  const [replacements, setReplacements] = useState<string[]>([])

  useEffect(() => {
    setReplacements(new Array(initialMentions.length).fill(""))
  }, [initialMentions])

  const handleSubmit = () => {
    // Replace each modified mention across the full transcript. This
    // mirrors the CLI behavior (utils/subject_review.py:_review_subjects_stdin):
    // a corrected name applies replace_all so every occurrence is
    // updated in one shot.
    let txt = initialTranscript
    initialMentions.forEach((m, i) => {
      const repl = (replacements[i] || "").trim()
      if (repl && repl !== m.name) {
        txt = txt.split(m.name).join(repl)
      }
    })
    onConfirm(txt)
  }

  const nSuspect = initialMentions.filter((m) => m.suspect).length
  const nEdited = replacements.filter((r) => r.trim()).length

  return (
    <Dialog open={open}>
      <DialogContent size="xl">
        <DialogHeader>
          <DialogTitle>校對 STT 主體</DialogTitle>
          <DialogDescription>
            STT 轉錄完成；確認所有專有名詞（公司、人名、機構、課程）有沒有聽錯。
            {nSuspect > 0 && (
              <>
                {" "}
                <Badge variant="warning" className="ml-1">
                  <AlertTriangle className="h-3 w-3" /> {nSuspect} 條疑似錯字
                </Badge>
              </>
            )}
          </DialogDescription>
        </DialogHeader>

        <DialogBody className="space-y-2">
          {initialMentions.length === 0 ? (
            <div className="text-sm text-[var(--color-muted-fg)] text-center py-6">
              沒有偵測到專有名詞 — 直接繼續。
            </div>
          ) : (
            initialMentions.map((m, i) => (
              <div
                key={i}
                className="rounded-md border border-[var(--color-border)] p-3 flex items-center gap-3"
              >
                <div className="shrink-0 min-w-[7rem]">
                  <div className="flex items-center gap-2">
                    {m.suspect ? (
                      <AlertTriangle className="h-3.5 w-3.5 text-amber-500" />
                    ) : (
                      <CheckCircle2 className="h-3.5 w-3.5 text-[var(--color-muted-fg)]" />
                    )}
                    <span className="font-medium text-sm">{m.name}</span>
                  </div>
                </div>
                <div className="flex-1 text-xs text-[var(--color-muted-fg)] italic line-clamp-2">
                  {m.context || "（沒有 context）"}
                </div>
                <input
                  type="text"
                  value={replacements[i] || ""}
                  onChange={(e) => {
                    const next = [...replacements]
                    next[i] = e.target.value
                    setReplacements(next)
                  }}
                  placeholder="正確寫法（留空 = 原本就對）"
                  className="w-44 h-8 rounded-md border border-[var(--color-input)] bg-[var(--color-bg)] px-2 text-xs"
                />
              </div>
            ))
          )}
        </DialogBody>

        <DialogFooter>
          <Button variant="ghost" onClick={onCancel} disabled={submitting}>
            略過校稿
          </Button>
          <Button variant="accent" disabled={submitting} onClick={handleSubmit}>
            {submitting ? "送出中…" : `確認${nEdited > 0 ? `（修正 ${nEdited} 條）` : ""}`}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
