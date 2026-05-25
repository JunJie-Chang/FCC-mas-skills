/**
 * TanStack Router setup (code-based — file-based is fine but overkill
 * for the small route set).
 *
 * Routes:
 *   /             redirect → /new
 *   /new          NewJobPage (text-input single agent)
 *   /new-audio    NewAudioPage (STT-driven multi-task pipeline)
 *   /jobs         "Coming soon" (history is Phase 6)
 *   /jobs/$jobId  JobDetailPage
 */
import {
  createRootRoute,
  createRoute,
  createRouter,
  Outlet,
  redirect,
} from "@tanstack/react-router"
import { Shell } from "@/components/layout/Shell"
import { NewJobPage } from "@/routes/NewJob"
import { NewAudioPage } from "@/routes/NewAudio"
import { NewTranslationPage } from "@/routes/NewTranslation"
import { JobDetailPage } from "@/routes/JobDetail"
import { ComingSoonPage } from "@/routes/Comingsoon"

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
  beforeLoad: () => { throw redirect({ to: "/new" }) },
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

const jobsIndexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/jobs",
  component: () => <ComingSoonPage name="任務歷史" />,
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
  jobsIndexRoute,
  jobDetailRoute,
])

export const router = createRouter({ routeTree })

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router
  }
}
