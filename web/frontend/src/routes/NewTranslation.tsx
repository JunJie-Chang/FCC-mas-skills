/**
 * /new-translation — submit an English (or other foreign-language)
 * article for Traditional Chinese translation.
 *
 * The translation_agent's run() takes structured input rather than a
 * free-text instruction; the router (server-side) parses task.instruction
 * as JSON. So this page packs {title, source, body_text, pub_date} into
 * the instruction field before POST /jobs.
 */
import { useState } from "react"
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
import { AlertCircle, Loader2, Send } from "lucide-react"

const schema = z.object({
  title:     z.string().min(1, "標題必填").max(500),
  source:    z.string().max(120).optional().default(""),
  pub_date:  z.string().optional().default(""),   // YYYY-MM-DD; agent fills today when blank
  body_text: z.string().min(1, "正文必填").max(80_000),
  intern_name: z.string().min(1).max(128),
})

type FormValues = z.infer<typeof schema>

export function NewTranslationPage() {
  const navigate = useNavigate()
  const create = useCreateJob()
  const [submitError, setSubmitError] = useState<string | null>(null)

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      title:       "",
      source:      "",
      pub_date:    "",
      body_text:   "",
      intern_name: "Justin",
    },
  })
  const { register, handleSubmit, watch, formState: { errors } } = form

  const onSubmit = handleSubmit(async (v) => {
    setSubmitError(null)
    // router.dispatch parses task.instruction as JSON for translation.
    // pub_date defaults to today in the agent if absent.
    const payload = {
      title:     v.title,
      source:    v.source,
      body_text: v.body_text,
      ...(v.pub_date ? { pub_date: v.pub_date } : {}),
    }
    try {
      const job = await create.mutateAsync({
        type:        "translation",
        instruction: JSON.stringify(payload),
        intern_name: v.intern_name,
        mode:        "short",   // translation_agent ignores mode but the API requires it
        extra:       {},
      })
      navigate({ to: "/jobs/$jobId", params: { jobId: job.id } })
    } catch (e) {
      setSubmitError(e instanceof Error ? e.message : String(e))
    }
  })

  const bodyLen = watch("body_text").length

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">翻譯任務</h1>
        <p className="text-sm text-[var(--color-muted-fg)] mt-1">
          外文文章逐段翻譯為繁體中文，輸出檔名格式 <code className="text-xs">YYYY.MM.DD_Title_Source_Intern.docx</code>。
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
            <CardTitle className="text-base">文章資訊</CardTitle>
            <CardDescription>
              題目與來源會出現在報告開頭。發布日期可留空（默認今天）。
            </CardDescription>
          </CardHeader>
          <CardContent className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="space-y-2 md:col-span-2">
              <Label htmlFor="title">標題</Label>
              <Input id="title" placeholder="Apple Q4 Earnings Strong" {...register("title")} />
              {errors.title && <p className="text-xs text-[var(--color-destructive)]">{errors.title.message}</p>}
            </div>
            <div className="space-y-2">
              <Label htmlFor="source">來源</Label>
              <Input id="source" placeholder="Reuters / FT / WSJ News" {...register("source")} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="pub_date">發布日期</Label>
              <Input id="pub_date" type="date" {...register("pub_date")} />
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">原文內容</CardTitle>
            <CardDescription>
              貼上完整文章。每段對應一個翻譯段；段落結構會被保留。
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <Textarea
              {...register("body_text")}
              placeholder="Apple reported strong quarterly earnings, driven by iPhone sales..."
              className="min-h-[260px] font-sans"
            />
            <div className="flex items-center justify-between text-xs">
              <span className={errors.body_text ? "text-[var(--color-destructive)]" : "text-[var(--color-muted-fg)]"}>
                {errors.body_text?.message ?? "原文可中英混雜；逐段翻譯時自動忽略空段"}
              </span>
              <span className="text-[var(--color-muted-fg)]">{bodyLen.toLocaleString()} 字</span>
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
              <p className="text-xs text-[var(--color-muted-fg)]">用於檔名後綴與報告署名。</p>
            </div>
          </CardContent>
        </Card>

        <div className="flex justify-end">
          <Button type="submit" variant="accent" size="lg" disabled={create.isPending}>
            {create.isPending ? (
              <><Loader2 className="h-4 w-4 animate-spin" /> 送出中…</>
            ) : (
              <><Send className="h-4 w-4" /> 送出翻譯</>
            )}
          </Button>
        </div>
      </form>
    </div>
  )
}
