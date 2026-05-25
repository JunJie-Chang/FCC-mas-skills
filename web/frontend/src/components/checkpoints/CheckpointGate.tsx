/**
 * CheckpointGate — driver for the three interactive checkpoint modals.
 *
 * Responsibilities:
 *   - Watch the SSE event list + job.status for an open checkpoint
 *   - Pick the right modal based on the most recent `*_request` event
 *     that has NOT been paired with its `*_resolved`
 *   - On user submit, POST /jobs/{id}/confirm with the right body shape
 *     and invalidate the job query so status flips back to running
 *
 * This component renders nothing when no checkpoint is open.
 */
import { useEffect, useMemo, useState } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { api, type JobResponse } from "@/api/client"
import { jobKeys } from "@/api/hooks"
import type { JobEvent } from "@/api/useJobEvents"
import {
  PlannerConfirmModal, type PlanTaskDraft,
} from "./PlannerConfirmModal"
import {
  SubjectReviewModal, type SubjectMention,
} from "./SubjectReviewModal"
import {
  SlideConfirmModal, type SlidePlanEntry,
} from "./SlideConfirmModal"

interface Props {
  job: JobResponse
  events: JobEvent[]
}

type OpenCheckpoint =
  | { kind: "confirm_tasks"; payload: { tasks: PlanTaskDraft[] } }
  | { kind: "subject_review"; payload: { transcript: string; mentions: SubjectMention[] } }
  | { kind: "slide_confirm"; payload: { slides_plan: SlidePlanEntry[]; topic: string; generate_images: boolean } }
  | null

/**
 * Walk the event stream once and figure out which (if any) checkpoint
 * is currently open. A *_request opens it; the matching *_resolved
 * (or any terminal job event) closes it.
 */
function selectOpenCheckpoint(events: JobEvent[]): OpenCheckpoint {
  let open: OpenCheckpoint = null
  for (const e of events) {
    switch (e.kind) {
      case "confirm_tasks_request":
        open = {
          kind: "confirm_tasks",
          payload: (e.payload.payload as { tasks: PlanTaskDraft[] }) ?? { tasks: [] },
        }
        break
      case "subject_review_request":
        open = {
          kind: "subject_review",
          payload: (e.payload.payload as { transcript: string; mentions: SubjectMention[] }) ?? { transcript: "", mentions: [] },
        }
        break
      case "slide_confirm_request":
        open = {
          kind: "slide_confirm",
          payload: (e.payload.payload as { slides_plan: SlidePlanEntry[]; topic: string; generate_images: boolean }) ?? { slides_plan: [], topic: "", generate_images: true },
        }
        break
      case "confirm_tasks_resolved":
      case "subject_review_resolved":
      case "slide_confirm_resolved":
      case "job_completed":
      case "job_failed":
      case "job_cancelled":
        open = null
        break
    }
  }
  return open
}

export function CheckpointGate({ job, events }: Props) {
  const qc = useQueryClient()
  const checkpoint = useMemo(() => selectOpenCheckpoint(events), [events])

  // Track which checkpoint instance is "live" so re-renders don't
  // reset modal-local state mid-edit. We key on the count of
  // *_request events seen so each new pause gets a fresh modal.
  const [openSeq, setOpenSeq] = useState(0)
  useEffect(() => {
    const reqCount = events.filter((e) => e.kind.endsWith("_request")).length
    setOpenSeq(reqCount)
  }, [events])

  const submit = useMutation({
    mutationFn: async (body: Record<string, unknown>) => {
      return await api.submitConfirm(job.id, body)
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: jobKeys.detail(job.id) })
    },
  })

  if (!checkpoint) return null

  if (checkpoint.kind === "confirm_tasks") {
    return (
      <PlannerConfirmModal
        key={`confirm-${openSeq}`}
        open
        initialTasks={checkpoint.payload.tasks}
        submitting={submit.isPending}
        onConfirm={(tasks) => submit.mutate({ action: "confirm", tasks })}
        onCancel={() => submit.mutate({ action: "cancel" })}
      />
    )
  }

  if (checkpoint.kind === "subject_review") {
    return (
      <SubjectReviewModal
        key={`subject-${openSeq}`}
        open
        initialTranscript={checkpoint.payload.transcript}
        initialMentions={checkpoint.payload.mentions}
        submitting={submit.isPending}
        onConfirm={(transcript) => submit.mutate({ transcript })}
        onCancel={() => submit.mutate({ transcript: checkpoint.payload.transcript })}
      />
    )
  }

  // slide_confirm
  return (
    <SlideConfirmModal
      key={`slides-${openSeq}`}
      open
      slidesPlan={checkpoint.payload.slides_plan}
      topic={checkpoint.payload.topic}
      generateImages={checkpoint.payload.generate_images}
      submitting={submit.isPending}
      onConfirm={() => submit.mutate({ proceed: true })}
      onCancel={() => submit.mutate({ proceed: false })}
    />
  )
}
