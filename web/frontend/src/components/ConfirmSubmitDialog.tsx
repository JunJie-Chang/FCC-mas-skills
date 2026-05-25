/**
 * ConfirmSubmitDialog — last gate before POST /jobs burns API credit.
 *
 * Forms use this when a misparse / wrong input would cost real money
 * (podcast misparsed = N wasted Tavily searches + Haiku calls;
 * speech_ppt misparsed = N wasted DALL-E images at $0.04 each).
 *
 * Each form renders its own `summary` slot — agent-specific preview
 * of what's about to be sent. The dialog itself is just chrome:
 * title, summary, optional cost line, two buttons.
 */
import { type ReactNode } from "react"
import {
  Dialog, DialogBody, DialogContent, DialogFooter, DialogHeader,
  DialogTitle, DialogDescription,
} from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { Loader2, Send } from "lucide-react"

interface Props {
  open: boolean
  title: string
  description?: string
  /** Per-form preview (e.g. parsed topic + N questions). */
  summary: ReactNode
  /** "預估成本 ~$0.30" — shown above buttons; hidden if absent. */
  estimatedCost?: string
  /** Disables confirm button + shows spinner while POST /jobs is in flight. */
  submitting: boolean
  onConfirm: () => void
  onCancel: () => void
  confirmLabel?: string
}

export function ConfirmSubmitDialog({
  open, title, description, summary, estimatedCost, submitting,
  onConfirm, onCancel, confirmLabel = "確認送出",
}: Props) {
  // Wire Radix's onOpenChange to onCancel so the X button, Esc key,
  // and backdrop click all dismiss the dialog. Without this, Radix
  // fires the close event but the controlled `open` prop never
  // flips false and the dialog appears stuck. Submitting blocks
  // dismissal — once POST /jobs is in flight, the user should wait.
  const handleOpenChange = (next: boolean) => {
    if (!next && !submitting) onCancel()
  }
  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent size="xl">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          {description && <DialogDescription>{description}</DialogDescription>}
        </DialogHeader>

        <DialogBody className="space-y-4">
          {summary}
        </DialogBody>

        <DialogFooter>
          {estimatedCost && (
            <div className="text-xs text-[var(--color-muted-fg)] mr-auto">
              {estimatedCost}
            </div>
          )}
          <Button variant="ghost" onClick={onCancel} disabled={submitting}>
            返回修改
          </Button>
          <Button variant="accent" disabled={submitting} onClick={onConfirm}>
            {submitting ? (
              <><Loader2 className="h-4 w-4 animate-spin" /> 送出中…</>
            ) : (
              <><Send className="h-4 w-4" /> {confirmLabel}</>
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
