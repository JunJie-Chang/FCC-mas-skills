/**
 * Thin typed fetch wrapper for the FastAPI backend.
 *
 * The full OpenAPI-derived types live in `generated.ts` (refreshed via
 * `npm run api:types`). This file is the hand-written surface that
 * components use — kept narrow on purpose so renames in generated
 * types only ripple through one file.
 */
import type { components } from "./generated"

export type JobStatus = components["schemas"]["JobStatus"]
export type JobResponse = components["schemas"]["JobResponse"]
export type JobCreateRequest = components["schemas"]["JobCreateRequest"]
export type JobSubTaskResponse = components["schemas"]["JobSubTaskResponse"]
export type UploadResponse = components["schemas"]["UploadResponse"]
export type JobsListResponse = components["schemas"]["JobsListResponse"]
export type StatsSummary = components["schemas"]["StatsSummary"]
// JobType (the wider union including stt_pipeline) is inlined into
// JobCreateRequest["type"]; AgentType is the narrower concrete-agent
// set, used by the sub-task table and the new-job picker.
export type JobType = JobCreateRequest["type"]
export type AgentType = JobSubTaskResponse["agent_type"]

const BASE = "/api"

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const init: RequestInit = {
    method,
    headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  }
  const res = await fetch(`${BASE}${path}`, init)
  if (!res.ok) {
    // FastAPI returns {detail: "..."} for HTTPException — surface that
    // verbatim so the UI can show meaningful messages instead of "500".
    let detail = `${method} ${path} → ${res.status}`
    try {
      const j = (await res.json()) as { detail?: string }
      if (j.detail) detail = j.detail
    } catch {
      /* response wasn't JSON — keep the default message */
    }
    throw new Error(detail)
  }
  // 204 No Content is rare here but possible — fall back to {}.
  if (res.status === 204) return {} as T
  return (await res.json()) as T
}

export const api = {
  createJob: (body: JobCreateRequest) =>
    request<JobResponse>("POST", "/jobs", body),

  getJob: (jobId: string) =>
    request<JobResponse>("GET", `/jobs/${jobId}`),

  /** Paginated history with filters + search. */
  listJobs: (params: {
    limit?: number; offset?: number;
    type?: string; status?: string; intern_name?: string;
    search?: string; date_from?: string; date_to?: string;
  } = {}) => {
    const qs = new URLSearchParams()
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== null && v !== "") qs.append(k, String(v))
    }
    const q = qs.toString()
    return request<JobsListResponse>("GET", `/jobs${q ? `?${q}` : ""}`)
  },

  /** Dashboard aggregate stats. */
  getStatsSummary: (days = 30) =>
    request<StatsSummary>("GET", `/stats/summary?days=${days}`),

  /**
   * Download a job's .docx as a Blob (so the browser can trigger save).
   * Returns the suggested filename from Content-Disposition when present.
   */
  downloadOutput: async (jobId: string): Promise<{ blob: Blob; filename: string }> => {
    const res = await fetch(`${BASE}/jobs/${jobId}/download`)
    if (!res.ok) throw new Error(`download failed: ${res.status}`)
    const cd = res.headers.get("Content-Disposition") || ""
    const match = cd.match(/filename\*?=(?:UTF-8'')?"?([^"]+)"?/i)
    const filename = match?.[1] ? decodeURIComponent(match[1]) : `job-${jobId}.docx`
    return { blob: await res.blob(), filename }
  },

  /** Plain-text log fetch for the inline viewer. */
  getLog: async (jobId: string): Promise<string> => {
    const res = await fetch(`${BASE}/jobs/${jobId}/log`)
    if (!res.ok) throw new Error(`log fetch failed: ${res.status}`)
    return res.text()
  },

  /**
   * Submit a user decision for whichever checkpoint the job is
   * currently waiting on. Body shape depends on the checkpoint kind
   * — see web/api/routes/jobs.py:submit_confirm for the contract.
   */
  submitConfirm: (jobId: string, body: Record<string, unknown>) =>
    request<JobResponse>("POST", `/jobs/${jobId}/confirm`, body),

  /** Cancel a running or awaiting job. */
  cancelJob: (jobId: string) =>
    request<JobResponse>("POST", `/jobs/${jobId}/cancel`),

  /** List sub-tasks of an stt_pipeline parent job. */
  listSubtasks: (jobId: string) =>
    request<JobSubTaskResponse[]>("GET", `/jobs/${jobId}/subtasks`),

  /** Download a single sub-task's output document. */
  downloadSubtask: async (subtaskId: string): Promise<{ blob: Blob; filename: string }> => {
    const res = await fetch(`${BASE}/jobs/subtasks/${subtaskId}/download`)
    if (!res.ok) throw new Error(`download failed: ${res.status}`)
    const cd = res.headers.get("Content-Disposition") || ""
    const match = cd.match(/filename\*?=(?:UTF-8'')?"?([^"]+)"?/i)
    const filename = match?.[1] ? decodeURIComponent(match[1]) : `subtask-${subtaskId}.docx`
    return { blob: await res.blob(), filename }
  },

  /** Upload an audio file via multipart. Reports progress via the
   *  optional onProgress callback. Uses XMLHttpRequest because the
   *  fetch API doesn't expose upload-progress events. */
  uploadAudio: (
    file: File,
    onProgress?: (sent: number, total: number) => void,
  ): Promise<UploadResponse> => {
    return new Promise((resolve, reject) => {
      const form = new FormData()
      form.append("file", file, file.name)
      const xhr = new XMLHttpRequest()
      xhr.open("POST", `${BASE}/uploads/audio`)
      xhr.responseType = "json"
      if (onProgress) {
        xhr.upload.onprogress = (e) => {
          if (e.lengthComputable) onProgress(e.loaded, e.total)
        }
      }
      xhr.onerror = () => reject(new Error("upload network error"))
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          resolve(xhr.response as UploadResponse)
        } else {
          const detail = (xhr.response as { detail?: string } | null)?.detail
            ?? `upload failed: ${xhr.status}`
          reject(new Error(detail))
        }
      }
      xhr.send(form)
    })
  },
}
