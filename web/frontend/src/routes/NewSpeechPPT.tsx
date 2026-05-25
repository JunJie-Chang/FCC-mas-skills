/**
 * /new-speech-ppt — structured Speech PPT submission.
 *
 * speech_ppt_agent.parse_script (Opus) accepts a transcript with
 * "第一頁:" / "第二頁:" markers. This form lets the user fill one
 * card per slide (title + content), and we format into that text
 * shape on submit — so the agent's parser sees clean structured input
 * and pages already arrive in the right order.
 *
 * Submits with type="speech_ppt" and extra.generate_images.
 *
 * Cost preview shown in the footer:
 *   N structured slides × $0.04 DALL-E = $X.YY  (skipped if toggle off)
 */
import { useFieldArray, useForm } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { z } from "zod"
import { useNavigate } from "@tanstack/react-router"
import { useState } from "react"
import { useCreateJob } from "@/api/hooks"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import {
  AlertCircle, ImageOff, ImagePlus, Loader2, Plus, Send, Trash2,
} from "lucide-react"

const DALLE_PER_IMAGE_USD = 0.04

const schema = z.object({
  topic:           z.string().max(200).optional().default(""),
  intern_name:     z.string().min(1).max(128),
  generate_images: z.boolean(),
  slides: z.array(z.object({
    title:   z.string().min(1, "標題不能空").max(120),
    content: z.string().min(1, "內容不能空").max(2000),
  }))
  .min(1, "至少一張投影片")
  .max(20, "最多 20 張"),
})

type FormValues = z.infer<typeof schema>

const _CN_NUMBERS = ["一","二","三","四","五","六","七","八","九","十",
                     "十一","十二","十三","十四","十五","十六","十七","十八","十九","二十"]

function formatInstruction(values: FormValues): string {
  const lines: string[] = []
  if (values.topic.trim()) {
    lines.push(`演講主題：${values.topic.trim()}`)
    lines.push("")
  }
  values.slides.forEach((s, i) => {
    const idxLabel = _CN_NUMBERS[i] ?? String(i + 1)
    // The agent's parser tolerates both colon styles. Using the
    // full-width form (：) to match the CLI examples in CLAUDE.md.
    lines.push(`第${idxLabel}頁：${s.title.trim()}`)
    lines.push(s.content.trim())
    lines.push("")
  })
  return lines.join("\n").trim()
}

export function NewSpeechPPTPage() {
  const navigate = useNavigate()
  const create = useCreateJob()
  const [submitError, setSubmitError] = useState<string | null>(null)

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      topic:           "",
      intern_name:     "Justin",
      generate_images: true,
      slides: [
        { title: "", content: "" },
        { title: "", content: "" },
        { title: "", content: "" },
      ],
    },
  })
  const { register, handleSubmit, watch, setValue, control, formState: { errors } } = form
  const { fields, append, remove } = useFieldArray({ control, name: "slides" })

  const generateImages = watch("generate_images")
  const slides = watch("slides")
  const nSlides = slides.length

  const onSubmit = handleSubmit(async (v) => {
    setSubmitError(null)
    const instruction = formatInstruction(v)
    try {
      const job = await create.mutateAsync({
        type:        "speech_ppt",
        instruction,
        intern_name: v.intern_name,
        mode:        "short",
        extra:       { generate_images: v.generate_images },
      })
      navigate({ to: "/jobs/$jobId", params: { jobId: job.id } })
    } catch (e) {
      setSubmitError(e instanceof Error ? e.message : String(e))
    }
  })

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">演講 PPT 任務</h1>
        <p className="text-sm text-[var(--color-muted-fg)] mt-1">
          每張投影片填標題 + 內容。送出後可在確認 modal 預覽圖片 prompt，再決定燒 DALL-E。
        </p>
      </div>

      {submitError && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>送出失敗</AlertTitle>
          <AlertDescription>{submitError}</AlertDescription>
        </Alert>
      )}

      <form onSubmit={onSubmit} className="space-y-6">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">演講主題（選填）</CardTitle>
            <CardDescription>
              留空時，agent 會用 Opus 自動從投影片內容推論主題。
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Input
              placeholder="例：台中智慧製造、台灣金融科技新樣態"
              {...register("topic")}
            />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">投影片清單（{fields.length}）</CardTitle>
            <CardDescription>
              每張結構化頁面會：1) 生成標題 + 5 條 bullet；2) 配一張 DALL-E 圖（若開啟）。
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {fields.map((field, idx) => (
              <div key={field.id} className="rounded-md border border-[var(--color-border)] p-3 space-y-2">
                <div className="flex items-center gap-2">
                  <span className="text-xs text-[var(--color-muted-fg)] tabular-nums shrink-0">
                    投影片 {idx + 1}
                  </span>
                  <Input
                    className="flex-1 h-8 text-sm"
                    placeholder="標題（例：智慧製造的定義）"
                    {...register(`slides.${idx}.title` as const)}
                  />
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="h-8 w-8 shrink-0"
                    onClick={() => remove(idx)}
                    disabled={fields.length === 1}
                    aria-label="刪除投影片"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                </div>
                <Textarea
                  className="min-h-[64px] text-sm"
                  placeholder="內容（自然描述即可，agent 會 normalise 成 5 條 bullet）"
                  {...register(`slides.${idx}.content` as const)}
                />
                {(errors.slides?.[idx]?.title || errors.slides?.[idx]?.content) && (
                  <p className="text-xs text-[var(--color-destructive)]">
                    {errors.slides[idx]?.title?.message ?? errors.slides[idx]?.content?.message}
                  </p>
                )}
              </div>
            ))}

            {typeof errors.slides?.message === "string" && (
              <p className="text-xs text-[var(--color-destructive)]">{errors.slides.message}</p>
            )}

            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => append({ title: "", content: "" })}
              disabled={fields.length >= 20}
              className="w-full"
            >
              <Plus className="h-3.5 w-3.5" />
              新增投影片
            </Button>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">圖片生成</CardTitle>
            <CardDescription>關閉可省 DALL-E 成本；只產出 PPT 結構 + bullets。</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => setValue("generate_images", true)}
                className={
                  "flex-1 rounded-md border px-4 py-3 text-sm transition-colors flex items-center justify-center gap-2 " +
                  (generateImages
                    ? "border-[var(--color-accent)] bg-[var(--color-accent)]/5 font-medium"
                    : "border-[var(--color-border)] hover:bg-[var(--color-muted)]")
                }
              >
                <ImagePlus className="h-4 w-4" />
                生成圖片
                <span className="text-xs text-[var(--color-muted-fg)]">
                  （預估 ${(nSlides * DALLE_PER_IMAGE_USD).toFixed(2)}）
                </span>
              </button>
              <button
                type="button"
                onClick={() => setValue("generate_images", false)}
                className={
                  "flex-1 rounded-md border px-4 py-3 text-sm transition-colors flex items-center justify-center gap-2 " +
                  (!generateImages
                    ? "border-[var(--color-accent)] bg-[var(--color-accent)]/5 font-medium"
                    : "border-[var(--color-border)] hover:bg-[var(--color-muted)]")
                }
              >
                <ImageOff className="h-4 w-4" />
                跳過圖片
              </button>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">執行設定</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-2 max-w-sm">
              <Label htmlFor="intern_name">實習生名稱</Label>
              <Input id="intern_name" {...register("intern_name")} />
            </div>
          </CardContent>
        </Card>

        <div className="flex justify-end">
          <Button type="submit" variant="accent" size="lg" disabled={create.isPending}>
            {create.isPending ? (
              <><Loader2 className="h-4 w-4 animate-spin" /> 送出中…</>
            ) : (
              <><Send className="h-4 w-4" /> 送出投影片任務</>
            )}
          </Button>
        </div>
      </form>
    </div>
  )
}
