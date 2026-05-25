/**
 * SlideConfirmModal — agent paused at speech_ppt.confirm_slides.
 *
 * Preview-then-proceed before burning DALL-E credits. Structured slides
 * show title + bullets; unstructured slides show the first few notes
 * lines. The footer surfaces the projected image-generation cost so the
 * user can decide whether to skip images on this run.
 */
import {
  Dialog, DialogBody, DialogContent, DialogDescription, DialogFooter,
  DialogHeader, DialogTitle,
} from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"

export interface SlidePlanEntry {
  type: "structured" | "unstructured"
  title: string
  bullets?: string[]
  notes?: string
}

interface Props {
  open: boolean
  slidesPlan: SlidePlanEntry[]
  topic: string
  generateImages: boolean
  submitting: boolean
  onConfirm: () => void
  onCancel: () => void
}

// Matches agents/speech_ppt_agent.py — DALL-E 3 standard size pricing.
const DALLE_PER_IMAGE_USD = 0.04

export function SlideConfirmModal({
  open, slidesPlan, topic, generateImages, submitting, onConfirm, onCancel,
}: Props) {
  const structured = slidesPlan.filter((s) => s.type === "structured")
  const unstructured = slidesPlan.filter((s) => s.type !== "structured")
  const projectedImageCost = generateImages
    ? structured.length * DALLE_PER_IMAGE_USD
    : 0

  return (
    <Dialog open={open}>
      <DialogContent size="xl">
        <DialogHeader>
          <DialogTitle>確認投影片計畫</DialogTitle>
          <DialogDescription>
            主題：{topic}．共 {slidesPlan.length} 張．
            {structured.length} 結構化（含圖）／{unstructured.length} 非結構化（僅備註）
          </DialogDescription>
        </DialogHeader>

        <DialogBody className="space-y-3">
          {slidesPlan.map((s, i) => (
            <div
              key={i}
              className="rounded-md border border-[var(--color-border)] p-3"
            >
              <div className="flex items-center gap-2 mb-1.5">
                <Badge variant="outline">{i + 1}</Badge>
                <Badge variant={s.type === "structured" ? "accent" : "muted"}>
                  {s.type === "structured" ? "結構化" : "非結構"}
                </Badge>
                <span className="font-medium text-sm">{s.title}</span>
              </div>
              {s.type === "structured" && s.bullets && (
                <ul className="ml-6 list-disc text-xs text-[var(--color-fg)] space-y-0.5">
                  {s.bullets.map((b, j) => (
                    <li key={j}>{b}</li>
                  ))}
                </ul>
              )}
              {s.type !== "structured" && s.notes && (
                <div className="ml-6 text-xs text-[var(--color-muted-fg)] whitespace-pre-line">
                  {s.notes.split("\n").slice(0, 3).join("\n")}
                  {s.notes.split("\n").length > 3 && "\n…"}
                </div>
              )}
            </div>
          ))}
        </DialogBody>

        <DialogFooter>
          <div className="text-xs text-[var(--color-muted-fg)] mr-auto">
            {generateImages
              ? `預估圖片成本：$${projectedImageCost.toFixed(2)}（${structured.length} 張 × DALL-E 3）`
              : "本次跳過圖片生成（生成 PPT 結構與 bullets）"}
          </div>
          <Button variant="ghost" onClick={onCancel} disabled={submitting}>
            取消
          </Button>
          <Button variant="accent" disabled={submitting} onClick={onConfirm}>
            {submitting ? "送出中…" : "確認生成"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
