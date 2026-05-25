/**
 * /new-podcast — structured Podcast research submission.
 *
 * Podcast tasks have a fixed shape: one topic + N questions. The
 * underlying agent (agents/podcast_agent.py) still runs Haiku in its
 * `parse_instruction` node to extract topic/questions from free text,
 * but pre-structuring at the form makes the user's intent explicit
 * (no semicolon-separated typos, no "and also..." parsing surprises).
 *
 * Submits with type="podcast" and instruction formatted as:
 *
 *     主題：{topic}
 *     問題：
 *     1. {q1}
 *     2. {q2}
 *     ...
 *
 * which podcast_agent.parse_instruction handles natively.
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
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import {
  AlertCircle, Loader2, Plus, Send, Trash2,
} from "lucide-react"

const schema = z.object({
  topic:       z.string().min(1, "主題必填").max(200),
  intern_name: z.string().min(1).max(128),
  questions:   z.array(z.object({ text: z.string().min(1, "問題不能空") }))
                .min(1, "至少一條問題")
                .max(8, "最多 8 條（更多請拆兩個 job）"),
})

type FormValues = z.infer<typeof schema>

function formatInstruction(topic: string, qs: string[]): string {
  const lines = [`主題：${topic}`, "問題："]
  qs.forEach((q, i) => lines.push(`${i + 1}. ${q.trim()}`))
  return lines.join("\n")
}

export function NewPodcastPage() {
  const navigate = useNavigate()
  const create = useCreateJob()
  const [submitError, setSubmitError] = useState<string | null>(null)

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      topic:       "",
      intern_name: "Justin",
      questions:   [{ text: "" }, { text: "" }, { text: "" }],
    },
  })
  const { register, handleSubmit, control, formState: { errors } } = form
  const { fields, append, remove } = useFieldArray({ control, name: "questions" })

  const onSubmit = handleSubmit(async (v) => {
    setSubmitError(null)
    const instruction = formatInstruction(v.topic, v.questions.map((q) => q.text))
    try {
      const job = await create.mutateAsync({
        type:        "podcast",
        instruction,
        intern_name: v.intern_name,
        mode:        "short",   // podcast agent ignores mode but the API requires it
        extra:       {},
      })
      navigate({ to: "/jobs/$jobId", params: { jobId: job.id } })
    } catch (e) {
      setSubmitError(e instanceof Error ? e.message : String(e))
    }
  })

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Podcast 任務</h1>
        <p className="text-sm text-[var(--color-muted-fg)] mt-1">
          一個主題 + N 個子問題。Agent 會為每題搜 3 篇一手新聞，逐篇翻譯與整理。
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
            <CardTitle className="text-base">主題</CardTitle>
            <CardDescription>用一句話描述本次 podcast 的主軸。</CardDescription>
          </CardHeader>
          <CardContent>
            <Input
              placeholder="例：全球媒體產業 / 台灣半導體 AI 深水區 / K-pop 商業模式"
              {...register("topic")}
            />
            {errors.topic && (
              <p className="text-xs text-[var(--color-destructive)] mt-2">{errors.topic.message}</p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">問題（{fields.length}）</CardTitle>
            <CardDescription>
              每題各自會搜 3 篇報導。最多 8 條 — 想做更多可拆成兩個 job。
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {fields.map((field, idx) => (
              <div key={field.id} className="flex items-start gap-2">
                <span className="w-6 h-9 flex items-center justify-center text-sm text-[var(--color-muted-fg)] tabular-nums shrink-0">
                  {idx + 1}
                </span>
                <div className="flex-1 min-w-0">
                  <Input
                    placeholder={`問題 ${idx + 1}`}
                    {...register(`questions.${idx}.text` as const)}
                  />
                  {errors.questions?.[idx]?.text && (
                    <p className="text-xs text-[var(--color-destructive)] mt-1">
                      {errors.questions[idx]?.text?.message}
                    </p>
                  )}
                </div>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="h-9 w-9 shrink-0"
                  onClick={() => remove(idx)}
                  disabled={fields.length === 1}
                  aria-label="刪除問題"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>
              </div>
            ))}

            {typeof errors.questions?.message === "string" && (
              <p className="text-xs text-[var(--color-destructive)]">{errors.questions.message}</p>
            )}

            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => append({ text: "" })}
              disabled={fields.length >= 8}
              className="w-full"
            >
              <Plus className="h-3.5 w-3.5" />
              新增問題
            </Button>
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
              <><Send className="h-4 w-4" /> 送出 Podcast 任務</>
            )}
          </Button>
        </div>
      </form>
    </div>
  )
}
