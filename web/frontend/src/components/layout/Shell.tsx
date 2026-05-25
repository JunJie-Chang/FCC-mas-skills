import { Link, useRouterState } from "@tanstack/react-router"
import { useTheme } from "@/stores/theme"
import { Button } from "@/components/ui/button"
import { Moon, Sun, FilePlus2, ListChecks } from "lucide-react"
import { cn } from "@/lib/utils"

interface NavItem {
  href: string
  label: string
  icon: React.ComponentType<{ className?: string }>
}

const NAV: NavItem[] = [
  { href: "/new", label: "新增任務", icon: FilePlus2 },
  // History route is Phase 6 (FRONTEND_PLAN.md §8). Stubbed in the nav
  // so the layout feels complete; landing on the page shows "coming soon".
  { href: "/jobs", label: "任務歷史", icon: ListChecks },
]

export function Shell({ children }: { children: React.ReactNode }) {
  const { theme, toggle } = useTheme()
  const path = useRouterState({ select: (s) => s.location.pathname })

  return (
    <div className="grid grid-cols-[16rem_1fr] grid-rows-[3.5rem_1fr] min-h-screen">
      {/* Sidebar */}
      <aside className="row-span-2 border-r border-[var(--color-border)] bg-[var(--color-card)] flex flex-col">
        <div className="h-14 flex items-center px-6 border-b border-[var(--color-border)]">
          <span className="font-semibold tracking-tight text-base">
            <span className="text-[var(--color-accent)]">FCC</span>
            <span className="text-[var(--color-muted-fg)]"> mas</span>
          </span>
        </div>
        <nav className="flex-1 px-3 py-4 flex flex-col gap-1">
          {NAV.map((item) => {
            const Icon = item.icon
            const active = path === item.href || path.startsWith(item.href + "/")
            return (
              <Link
                key={item.href}
                to={item.href}
                className={cn(
                  "flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors",
                  active
                    ? "bg-[var(--color-muted)] text-[var(--color-fg)] font-medium"
                    : "text-[var(--color-muted-fg)] hover:bg-[var(--color-muted)] hover:text-[var(--color-fg)]",
                )}
              >
                <Icon className="h-4 w-4" />
                {item.label}
              </Link>
            )
          })}
        </nav>
        <div className="px-6 py-4 border-t border-[var(--color-border)] text-xs text-[var(--color-muted-fg)]">
          Private &amp; Confidential
        </div>
      </aside>

      {/* Header */}
      <header className="border-b border-[var(--color-border)] bg-[var(--color-card)] flex items-center justify-between px-6">
        <div className="text-sm text-[var(--color-muted-fg)]">
          Internal research console · v0.1
        </div>
        <Button variant="ghost" size="icon" onClick={toggle} aria-label="Toggle theme">
          {theme === "light" ? <Moon className="h-4 w-4" /> : <Sun className="h-4 w-4" />}
        </Button>
      </header>

      {/* Main */}
      <main className="overflow-auto">
        <div className="max-w-5xl mx-auto px-8 py-8">
          {children}
        </div>
      </main>
    </div>
  )
}
