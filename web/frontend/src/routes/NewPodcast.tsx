/**
 * /new-podcast — Podcast research submission.
 *
 * The realistic input flow at FCC: someone forwards a chunk of text
 * with a topic header and a numbered question list:
 *
 *     Podcast: 張雪機車
 *     1. 中國機車最近震撼全球…
 *     2. WSBK 過去長期由歐洲與日本品牌主導…
 *     ...
 *
 * Rather than make the user re-type each question into separate
 * inputs, we accept the raw block and pass it straight through —
 * podcast_agent.parse_instruction (Haiku) already extracts topic +
 * questions from arbitrary text shapes. We do a quick client-side
 * regex pass purely to show "已偵測：1 主題 + N 題" feedback so the
 * user can sanity-check the parse before submitting.
 */
import { useMemo, useState } from "react"
import { useForm } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { z } from "zod"
import { useNavigate } from "@tanstack/react-router"
import { useCreateJob } from "@/api/hooks"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { AlertCircle, AlertTriangle, CheckCircle2, Loader2, Send } from "lucide-react"

const schema = z.object({
  instruction: z.string().min(10, "請貼上完整主題與問題").max(20_000),
  intern_name: z.string().min(1).max(128),
})

type FormValues = z.infer<typeof schema>


/**
 * Light client-side parse just for UI feedback. Doesn't gate submit —
 * the source of truth is the agent's Haiku parser; this is purely a
 * "did we paste something sensible" sanity check.
 *
 * Heuristics:
 *   - Topic line: starts with "Podcast"/"主題"/"題目" (any case) OR
 *     is just a short first non-empty line followed by numbered items
 *   - Questions: lines starting with "1." / "2." / "(1)" / "1、" etc.
 *
 * Failure mode is OK — if it can't detect, we show 0/0 and let the
 * user submit anyway (agent will parse).
 */
function detectStructure(text: string): { topic: string; questionCount: number } {
  const lines = text.split("\n").map((l) => l.trim()).filter(Boolean)
  if (lines.length === 0) return { topic: "", questionCount: 0 }

  // Topic detection: explicit prefix, else first short non-numbered line.
  let topic = ""
  for (const line of lines) {
    const m = line.match(/^(?:podcast|主題|題目|topic)\s*[:：]\s*(.+)$/i)
    if (m && m[1]) {
      topic = m[1].trim()
      break
    }
  }
  if (!topic && lines[0]) {
    // Fallback: first line if it isn't itself a numbered question
    if (!/^\s*(?:\d+[.、)）]|\(\d+\))/.test(lines[0]) && lines[0].length <= 100) {
      topic = lines[0]
    }
  }

  // Count numbered question lines. Tolerate `1.` / `1、` / `1)` /
  // `(1)` / `1．` (full-width).
  const questionCount = lines.filter((l) =>
    /^\s*(?:\d+[.、)．）]|\(\d+\))\s+\S/.test(l)
  ).length

  return { topic, questionCount }
}


const EXAMPLE_PLACEHOLDER = `Podcast: 張雪機車
1. 中國機車最近震撼全球，張雪機車最近連奪 5 個國際機車大賽冠軍，請說明其驚人紀錄
2. WSBK 過去長期由歐洲與日本品牌主導，為何張雪機車這次奪冠⋯
3. ⋯`


export function NewPodcastPage() {
  const navigate = useNavigate()
  const create = useCreateJob()
  const [submitError, setSubmitError] = useState<string | null>(null)

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      instruction: "",
      intern_name: "Justin",
    },
  })
  const { register, handleSubmit, watch, formState: { errors } } = form

  const instructionText = watch("instruction")
  const detected = useMemo(() => detectStructure(instructionText), [instructionText])

  const onSubmit = handleSubmit(async (v) => {
    setSubmitError(null)
    try {
      const job = await create.mutateAsync({
        type:        "podcast",
        instruction: v.instruction,
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
          直接貼上主題 + 編號問題清單。Agent 會為每題搜 3 篇一手新聞，逐篇翻譯整理。
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
            <CardTitle className="text-base">任務內容</CardTitle>
            <CardDescription>
              將整段「主題 + 編號問題」貼進來。常見格式：第一行寫
              <code className="px-1 mx-0.5 text-xs">Podcast: 主題</code>，接著
              <code className="px-1 mx-0.5 text-xs">1. 問題</code>
              <code className="px-1 mx-0.5 text-xs">2. 問題</code> ⋯
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <Textarea
              {...register("instruction")}
              placeholder={EXAMPLE_PLACEHOLDER}
              className="min-h-[280px] font-sans leading-relaxed"
            />

            {/* Live detection feedback — purely informational, not a gate */}
            {instructionText.trim().length > 0 && (
              <ParseFeedback
                topic={detected.topic}
                questionCount={detected.questionCount}
              />
            )}

            {errors.instruction && (
              <p className="text-xs text-[var(--color-destructive)]">
                {errors.instruction.message}
              </p>
            )}
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


/**
 * Inline strip showing what the client-side regex detected. Green when
 * we see both a topic AND at least one numbered question; amber-ish
 * warning when one of them is missing (user can still submit — the
 * agent's Haiku is more forgiving than our regex).
 */
function ParseFeedback({
  topic, questionCount,
}: { topic: string; questionCount: number }) {
  const looksGood = topic.length > 0 && questionCount > 0

  if (looksGood) {
    return (
      <div className="flex items-start gap-2 text-xs text-emerald-700 dark:text-emerald-400 bg-emerald-500/10 rounded-md px-3 py-2">
        <CheckCircle2 className="h-3.5 w-3.5 mt-0.5 shrink-0" />
        <div>
          <div>偵測到 <strong>{questionCount}</strong> 題，主題：「{topic}」</div>
          <div className="text-[var(--color-muted-fg)] mt-0.5">
            送出後 Haiku 會再次確認；偶有偵測差一兩題屬正常。
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="flex items-start gap-2 text-xs text-amber-700 dark:text-amber-400 bg-amber-500/10 rounded-md px-3 py-2">
      <AlertTriangle className="h-3.5 w-3.5 mt-0.5 shrink-0" />
      <div>
        {!topic && !questionCount && "沒偵測到主題或編號問題。仍可送出 — agent 會自己解析；但確認格式有點像範例的話比較不會跑偏。"}
        {topic && !questionCount && `主題已抓到（「${topic}」），但沒看到編號問題行（1. / 2. / …）`}
        {!topic && questionCount > 0 && `偵測到 ${questionCount} 題，但沒抓到主題行（可加一行「Podcast: XXX」）`}
      </div>
    </div>
  )
}
