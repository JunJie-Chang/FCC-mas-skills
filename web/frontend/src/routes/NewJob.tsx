import { useForm } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { z } from "zod"
import { useNavigate } from "@tanstack/react-router"
import { useCreateJob } from "@/api/hooks"
import type { AgentType } from "@/api/client"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Loader2, Send, AlertCircle } from "lucide-react"
import { useState } from "react"

const schema = z.object({
  type: z.enum([
    "company_info", "person_info", "translation", "letter", "meeting",
    "verbal_cleanup", "podcast", "speech_ppt",
  ]),
  instruction: z.string().min(1, "請輸入任務指令").max(20_000),
  intern_name: z.string().min(1).max(128),
  mode:        z.enum(["short", "medium"]),
})

type FormValues = z.infer<typeof schema>

// Phase 3 unlocks the remaining agent types. Translation stays disabled
// here because it needs structured input (title / source / body_text) —
// that flow lives on its own /new-translation page in the sidebar.
const TYPES: { value: AgentType; label: string; description: string; enabled: boolean; note?: string }[] = [
  { value: "company_info",   label: "公司研究",   description: "業務 / 財務 / 競爭定位",     enabled: true },
  { value: "person_info",    label: "人物背景",   description: "公司關係 / 履歷 / 背景",     enabled: true },
  { value: "podcast",        label: "Podcast",   description: "主題 + 多問題研究",         enabled: true },
  { value: "meeting",        label: "會議紀錄",   description: "口述會議整理（letter 共用）", enabled: true },
  { value: "verbal_cleanup", label: "口述清稿",   description: "去除廢話、整理書面稿",       enabled: true },
  { value: "speech_ppt",     label: "演講 PPT",  description: "結構化頁 + DALL-E 圖片",    enabled: true },
  { value: "translation",    label: "翻譯",       description: "外文文章中譯（含 title / 來源欄位）", enabled: false, note: "請走「翻譯任務」頁面" },
]

export function NewJobPage() {
  const create = useCreateJob()
  const navigate = useNavigate()
  const [submitError, setSubmitError] = useState<string | null>(null)

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      type:        "company_info",
      instruction: "",
      intern_name: "Justin",
      mode:        "short",
    },
  })
  const { register, handleSubmit, watch, setValue, formState: { errors } } = form
  const selectedType = watch("type")
  const instruction = watch("instruction")

  const onSubmit = handleSubmit(async (values) => {
    setSubmitError(null)
    try {
      const job = await create.mutateAsync({
        type:        values.type,
        instruction: values.instruction,
        intern_name: values.intern_name,
        mode:        values.mode,
        extra:       {},
      })
      navigate({ to: "/jobs/$jobId", params: { jobId: job.id } })
    } catch (e) {
      setSubmitError(e instanceof Error ? e.message : "未知錯誤")
    }
  })

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">新增任務</h1>
        <p className="text-sm text-[var(--color-muted-fg)] mt-1">
          選擇任務類型、寫下指令，送出後可即時看到 agent 執行進度。
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
        {/* Type picker */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">任務類型</CardTitle>
            <CardDescription>Phase 1 僅開放公司研究，其餘預計後續階段陸續啟用。</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
              {TYPES.map((t) => {
                const selected = selectedType === t.value
                return (
                  <button
                    key={t.value}
                    type="button"
                    disabled={!t.enabled}
                    onClick={() => setValue("type", t.value)}
                    className={
                      "text-left rounded-lg border p-4 transition-colors " +
                      (selected
                        ? "border-[var(--color-accent)] ring-2 ring-[var(--color-accent)] bg-[var(--color-accent)]/5"
                        : "border-[var(--color-border)] hover:bg-[var(--color-muted)]") +
                      (!t.enabled ? " opacity-50 cursor-not-allowed" : "")
                    }
                  >
                    <div className="flex items-center justify-between gap-2 mb-1">
                      <span className="font-medium text-sm">{t.label}</span>
                      {!t.enabled && (
                        <Badge variant="muted" className="shrink-0">{t.note ?? "後續開放"}</Badge>
                      )}
                    </div>
                    <p className="text-xs text-[var(--color-muted-fg)]">{t.description}</p>
                  </button>
                )
              })}
            </div>
          </CardContent>
        </Card>

        {/* Instruction */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">任務指令</CardTitle>
            <CardDescription>
              寫得明確 → 結果就會精準。可包含公司名、ticker、研究重點。
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <Textarea
              {...register("instruction")}
              placeholder="例：查 Apple 最新一季財報重點，關注 iPhone 區域營收與服務業務毛利率"
              className="min-h-[140px] font-sans"
            />
            <div className="flex items-center justify-between text-xs">
              <span className={errors.instruction ? "text-[var(--color-destructive)]" : "text-[var(--color-muted-fg)]"}>
                {errors.instruction?.message ?? "可使用中英文，沒有長度上限（建議 200 字內）"}
              </span>
              <span className="text-[var(--color-muted-fg)]">
                {instruction.length} 字
              </span>
            </div>
          </CardContent>
        </Card>

        {/* Options */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">執行設定</CardTitle>
          </CardHeader>
          <CardContent className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="intern_name">實習生名稱</Label>
              <Input id="intern_name" {...register("intern_name")} />
              <p className="text-xs text-[var(--color-muted-fg)]">
                用於檔名與報告署名。多人用逗號分隔。
              </p>
            </div>
            <div className="space-y-2">
              <Label>報告模式</Label>
              <div className="flex gap-2">
                {(["short", "medium"] as const).map((m) => (
                  <button
                    key={m}
                    type="button"
                    onClick={() => setValue("mode", m)}
                    className={
                      "flex-1 rounded-md border px-4 py-2 text-sm transition-colors " +
                      (watch("mode") === m
                        ? "border-[var(--color-accent)] bg-[var(--color-accent)]/5 font-medium"
                        : "border-[var(--color-border)] hover:bg-[var(--color-muted)]")
                    }
                  >
                    {m === "short" ? "Short（約兩頁）" : "Medium（延伸分析）"}
                  </button>
                ))}
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Submit */}
        <div className="flex justify-end gap-3">
          <Button type="submit" variant="accent" size="lg" disabled={create.isPending}>
            {create.isPending ? (
              <><Loader2 className="h-4 w-4 animate-spin" /> 送出中…</>
            ) : (
              <><Send className="h-4 w-4" /> 送出任務</>
            )}
          </Button>
        </div>
      </form>
    </div>
  )
}
