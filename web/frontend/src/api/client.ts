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
// AgentType is inlined into JobCreateRequest["type"] in the OpenAPI
// schema; export it under a more useful name here.
export type AgentType = JobCreateRequest["type"]

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
}
