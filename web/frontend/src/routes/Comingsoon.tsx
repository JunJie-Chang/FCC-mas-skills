import { Card, CardContent } from "@/components/ui/card"
import { Construction } from "lucide-react"

/** Placeholder for routes that exist in the nav but haven't been built yet
 *  (e.g. /jobs history view — Phase 6). Surfacing them in the sidebar
 *  keeps the layout honest about future scope. */
export function ComingSoonPage({ name }: { name: string }) {
  return (
    <Card>
      <CardContent className="py-16 flex flex-col items-center text-center gap-3">
        <Construction className="h-10 w-10 text-[var(--color-muted-fg)]" />
        <div className="text-lg font-medium">{name}</div>
        <p className="text-sm text-[var(--color-muted-fg)] max-w-md">
          這個功能在後續階段啟用。Phase 1 先聚焦於把單一任務的執行流程跑通。
        </p>
      </CardContent>
    </Card>
  )
}
