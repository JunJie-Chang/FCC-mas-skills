/**
 * TanStack Query hooks for the job lifecycle.
 *
 * Server state stays in the cache here — components read via these
 * hooks rather than passing data through props. Mutation hooks return
 * the standard tuple so route handlers can drive submit-then-navigate
 * flows.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { api, type JobCreateRequest } from "./client"

export const jobKeys = {
  all:     ["jobs"] as const,
  detail:  (id: string) => ["jobs", id] as const,
  log:     (id: string) => ["jobs", id, "log"] as const,
}

export function useJob(jobId: string | undefined) {
  return useQuery({
    queryKey: jobId ? jobKeys.detail(jobId) : ["jobs", "noop"],
    queryFn: () => api.getJob(jobId!),
    enabled: !!jobId,
    // Status transitions arrive via SSE; we invalidate on terminal
    // events. A 30s background refetch is a belt-and-braces safety net
    // for SSE-dropped sessions.
    refetchInterval: 30_000,
  })
}

export function useJobLog(jobId: string | undefined, enabled: boolean) {
  return useQuery({
    queryKey: jobId ? jobKeys.log(jobId) : ["jobs", "noop", "log"],
    queryFn: () => api.getLog(jobId!),
    enabled: !!jobId && enabled,
  })
}

export function useCreateJob() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: JobCreateRequest) => api.createJob(body),
    onSuccess: (job) => {
      qc.setQueryData(jobKeys.detail(job.id), job)
    },
  })
}

export function useInvalidateJob() {
  const qc = useQueryClient()
  return (jobId: string) => qc.invalidateQueries({ queryKey: jobKeys.detail(jobId) })
}

export interface JobListFilters {
  limit?: number
  offset?: number
  type?: string
  status?: string
  intern_name?: string
  search?: string
  date_from?: string
  date_to?: string
}

export function useJobList(filters: JobListFilters) {
  return useQuery({
    queryKey: ["jobs-list", filters],
    queryFn:  () => api.listJobs(filters),
    placeholderData: (prev) => prev,   // smooth re-fetch on filter change
  })
}

export function useStatsSummary(days = 30) {
  return useQuery({
    queryKey: ["stats", "summary", days],
    queryFn:  () => api.getStatsSummary(days),
    // Dashboard auto-refresh every 30s so a running task's cost
    // reflects in the headline number.
    refetchInterval: 30_000,
  })
}

export function useJobSubtasks(jobId: string | undefined, isStt: boolean) {
  return useQuery({
    queryKey: jobId ? ["jobs", jobId, "subtasks"] : ["jobs", "noop", "subtasks"],
    queryFn:  () => api.listSubtasks(jobId!),
    enabled:  !!jobId && isStt,
    // Sub-task rows churn during STT pipeline; refetch every 10s as a
    // safety net (frontend also invalidates on subtask_completed events).
    refetchInterval: 10_000,
  })
}
