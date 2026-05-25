/**
 * TanStack Router setup (code-based — file-based is fine but overkill
 * for the small route set).
 *
 * Routes:
 *   /             DashboardPage (recent jobs + spend + CTAs — Phase 6)
 *   /new          NewJobPage (text-input single agent)
 *   /new-audio    NewAudioPage (STT-driven multi-task pipeline)
 *   /new-podcast  NewPodcastPage
 *   /new-speech-ppt NewSpeechPPTPage
 *   /new-translation NewTranslationPage
 *   /jobs         JobsListPage (filter + search — Phase 6)
 *   /jobs/$jobId  JobDetailPage
 */
import {
  createRootRoute,
  createRoute,
  createRouter,
  Outlet,
} from "@tanstack/react-router"
import { Shell } from "@/components/layout/Shell"
import { DashboardPage } from "@/routes/Dashboard"
import { NewJobPage } from "@/routes/NewJob"
import { NewAudioPage } from "@/routes/NewAudio"
import { NewTranslationPage } from "@/routes/NewTranslation"
import { NewPodcastPage } from "@/routes/NewPodcast"
import { NewSpeechPPTPage } from "@/routes/NewSpeechPPT"
import { JobDetailPage } from "@/routes/JobDetail"
import { JobsListPage } from "@/routes/JobsList"

const rootRoute = createRootRoute({
  component: () => (
    <Shell>
      <Outlet />
    </Shell>
  ),
})

const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  component: DashboardPage,
})

const newJobRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/new",
  component: NewJobPage,
})

const newAudioRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/new-audio",
  component: NewAudioPage,
})

const newTranslationRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/new-translation",
  component: NewTranslationPage,
})

const newPodcastRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/new-podcast",
  component: NewPodcastPage,
})

const newSpeechPPTRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/new-speech-ppt",
  component: NewSpeechPPTPage,
})

const jobsIndexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/jobs",
  component: JobsListPage,
})

const jobDetailRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/jobs/$jobId",
  component: JobDetailPage,
})

const routeTree = rootRoute.addChildren([
  indexRoute,
  newJobRoute,
  newAudioRoute,
  newTranslationRoute,
  newPodcastRoute,
  newSpeechPPTRoute,
  jobsIndexRoute,
  jobDetailRoute,
])

export const router = createRouter({ routeTree })

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router
  }
}
