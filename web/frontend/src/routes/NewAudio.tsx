/**
 * /new-audio — submit a CY-style dictation as an STT-driven job.
 *
 * Flow on this page:
 *   1. User drops / picks an audio file.
 *   2. Frontend POSTs it as multipart with a progress bar (XHR, not
 *      fetch — fetch can't observe upload progress).
 *   3. Server returns {upload_id}.
 *   4. We POST /jobs with type="stt_pipeline" and extra.upload_id.
 *   5. Navigate to /jobs/$jobId. The backend's STT pipeline takes
 *      over from there (transcribe → subject_review modal →
 *      planner.confirm modal → dispatch fan-out → sub-task cards).
 */
import { useRef, useState } from "react"
import { useNavigate } from "@tanstack/react-router"
import { api, type UploadResponse } from "@/api/client"
import { useCreateJob } from "@/api/hooks"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import {
  AlertCircle, FileAudio, Loader2, Upload, X,
} from "lucide-react"

// OpenAI gpt-4o-transcribe accepts these; the backend's allow-list
// matches. Keep them in sync.
const ACCEPTED_EXTS = [".m4a", ".mp3", ".mp4", ".wav", ".webm"]
// Formats users WILL try but that OpenAI rejects — we explicitly call
// them out with a conversion hint instead of a generic "wrong format".
const KNOWN_REJECT_EXTS: Record<string, string> = {
  ".aiff": "AIFF (macOS say 預設輸出)",
  ".aif":  "AIFF (macOS say 預設輸出)",
  ".opus": "Opus",
  ".ogg":  "OGG Vorbis",
  ".flac": "FLAC",
  ".caf":  "Core Audio Format (iOS QuickTime)",
  ".wma":  "Windows Media Audio",
}
const MAX_BYTES = 100 * 1024 * 1024

function formatBytes(b: number): string {
  if (b < 1024) return `${b} B`
  if (b < 1024 * 1024) return `${(b / 1024).toFixed(1)} KB`
  return `${(b / 1024 / 1024).toFixed(1)} MB`
}

function extOf(name: string): string {
  const m = name.toLowerCase().match(/\.[a-z0-9]+$/)
  return m ? m[0] : ""
}

export function NewAudioPage() {
  const navigate = useNavigate()
  const create = useCreateJob()

  const [file, setFile] = useState<File | null>(null)
  const [intern, setIntern] = useState("Justin")
  const [mode, setMode] = useState<"short" | "medium">("short")

  const [uploading, setUploading] = useState(false)
  const [uploadPct, setUploadPct] = useState(0)
  const [upload, setUpload] = useState<UploadResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [dragOver, setDragOver] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const acceptFile = (f: File) => {
    const ext = extOf(f.name)

    // Format check FIRST so a 100 MB AIFF doesn't get past the size
    // check just to fail later on the wrong reason.
    if (!ext) {
      setError(`檔案 "${f.name}" 沒有副檔名，無法判斷格式。`)
      return
    }
    if (KNOWN_REJECT_EXTS[ext]) {
      setError(
        `${KNOWN_REJECT_EXTS[ext]} (${ext}) 不被 OpenAI STT 接受。` +
        `請先轉檔成 m4a / mp3 / wav。` +
        `指令範例：ffmpeg -i input${ext} -c:a aac -b:a 64k output.m4a`,
      )
      return
    }
    if (!ACCEPTED_EXTS.includes(ext)) {
      setError(`不支援的副檔名 ${ext}。支援格式：${ACCEPTED_EXTS.join(" / ")}`)
      return
    }

    if (f.size > MAX_BYTES) {
      setError(
        `檔案過大：${formatBytes(f.size)}（上限 ${MAX_BYTES / (1024 * 1024)} MB）。` +
        `可降位元率：ffmpeg -i input.m4a -b:a 64k -c:a aac smaller.m4a`,
      )
      return
    }

    setError(null)
    setFile(f)
    setUpload(null)
    setUploadPct(0)
  }

  const startUpload = async () => {
    if (!file) return
    setError(null)
    setUploading(true)
    setUploadPct(0)
    try {
      const resp = await api.uploadAudio(file, (sent, total) => {
        setUploadPct(Math.round((sent / total) * 100))
      })
      setUpload(resp)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setUploading(false)
    }
  }

  const submitJob = async () => {
    if (!upload) return
    setError(null)
    try {
      const job = await create.mutateAsync({
        type:        "stt_pipeline",
        instruction: `[STT] ${upload.filename}`,
        intern_name: intern,
        mode,
        extra:       { upload_id: upload.id },
      })
      navigate({ to: "/jobs/$jobId", params: { jobId: job.id } })
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">口述任務（STT）</h1>
        <p className="text-sm text-[var(--color-muted-fg)] mt-1">
          上傳錄音 → 自動轉錄 → 校對 STT 主體 → 解析任務 → 並行分派。
        </p>
      </div>

      {error && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>無法處理這個檔案</AlertTitle>
          <AlertDescription className="whitespace-pre-wrap">{error}</AlertDescription>
        </Alert>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="text-base">1. 上傳音檔</CardTitle>
          <CardDescription>
            支援 {ACCEPTED_EXTS.join(" / ")}．單檔上限 100 MB．
            AIFF / Opus / FLAC 等非 OpenAI 支援格式請先轉檔（前端會擋下並提示）．
            超過 4 分鐘的錄音由 ffmpeg 自動切片。
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Dropzone */}
          {!file ? (
            <div
              onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
              onDragLeave={() => setDragOver(false)}
              onDrop={(e) => {
                e.preventDefault()
                setDragOver(false)
                const f = e.dataTransfer.files[0]
                if (f) acceptFile(f)
              }}
              onClick={() => inputRef.current?.click()}
              className={
                "rounded-lg border-2 border-dashed p-10 text-center cursor-pointer transition-colors " +
                (dragOver
                  ? "border-[var(--color-accent)] bg-[var(--color-accent)]/5"
                  : "border-[var(--color-border)] hover:bg-[var(--color-muted)]")
              }
            >
              <FileAudio className="h-8 w-8 mx-auto mb-3 text-[var(--color-muted-fg)]" />
              <div className="text-sm font-medium">拖曳音檔到這裡，或點擊選取</div>
              <div className="text-xs text-[var(--color-muted-fg)] mt-1">
                {ACCEPTED_EXTS.join(" · ")}
              </div>
              <input
                ref={inputRef}
                type="file"
                accept={ACCEPTED_EXTS.join(",")}
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0]
                  if (f) acceptFile(f)
                }}
              />
            </div>
          ) : (
            <div className="rounded-md border border-[var(--color-border)] p-4 flex items-center gap-3">
              <FileAudio className="h-5 w-5 text-[var(--color-accent)] shrink-0" />
              <div className="flex-1 min-w-0">
                <div className="text-sm font-medium truncate">{file.name}</div>
                <div className="text-xs text-[var(--color-muted-fg)]">{formatBytes(file.size)}</div>
              </div>
              {!uploading && !upload && (
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={() => { setFile(null); setUpload(null) }}
                  aria-label="移除"
                >
                  <X className="h-4 w-4" />
                </Button>
              )}
            </div>
          )}

          {/* Upload progress */}
          {uploading && (
            <div className="space-y-1">
              <div className="h-2 rounded-full bg-[var(--color-muted)] overflow-hidden">
                <div
                  className="h-full bg-[var(--color-accent)] transition-all"
                  style={{ width: `${uploadPct}%` }}
                />
              </div>
              <div className="text-xs text-[var(--color-muted-fg)] text-right">
                上傳中 {uploadPct}%
              </div>
            </div>
          )}

          {upload && (
            <Alert>
              <AlertTitle>已上傳</AlertTitle>
              <AlertDescription>
                {upload.filename} · {formatBytes(upload.size_bytes)} · id={upload.id.slice(0, 8)}…
              </AlertDescription>
            </Alert>
          )}

          {file && !upload && (
            <Button onClick={startUpload} disabled={uploading} variant="accent">
              {uploading ? (
                <><Loader2 className="h-4 w-4 animate-spin" /> 上傳中…</>
              ) : (
                <><Upload className="h-4 w-4" /> 開始上傳</>
              )}
            </Button>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">2. 執行設定</CardTitle>
        </CardHeader>
        <CardContent className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="space-y-2">
            <Label htmlFor="intern_name">實習生名稱</Label>
            <Input
              id="intern_name"
              value={intern}
              onChange={(e) => setIntern(e.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label>報告模式（套用到全部子任務）</Label>
            <div className="flex gap-2">
              {(["short", "medium"] as const).map((m) => (
                <button
                  key={m}
                  type="button"
                  onClick={() => setMode(m)}
                  className={
                    "flex-1 rounded-md border px-4 py-2 text-sm transition-colors " +
                    (mode === m
                      ? "border-[var(--color-accent)] bg-[var(--color-accent)]/5 font-medium"
                      : "border-[var(--color-border)] hover:bg-[var(--color-muted)]")
                  }
                >
                  {m === "short" ? "Short" : "Medium"}
                </button>
              ))}
            </div>
          </div>
        </CardContent>
      </Card>

      <div className="flex justify-end">
        <Button
          variant="accent"
          size="lg"
          onClick={submitJob}
          disabled={!upload || create.isPending}
        >
          {create.isPending ? (
            <><Loader2 className="h-4 w-4 animate-spin" /> 送出中…</>
          ) : (
            "送出任務"
          )}
        </Button>
      </div>
    </div>
  )
}
