import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "@/lib/utils"

const badgeVariants = cva(
  "inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold transition-colors focus:outline-none",
  {
    variants: {
      variant: {
        default:    "border-transparent bg-[var(--color-primary)] text-[var(--color-primary-fg)]",
        secondary:  "border-transparent bg-[var(--color-secondary)] text-[var(--color-secondary-fg)]",
        accent:     "border-transparent bg-[var(--color-accent)] text-[var(--color-accent-fg)]",
        outline:    "border-[var(--color-border)] text-[var(--color-fg)]",
        success:    "border-transparent bg-emerald-500/15 text-emerald-700 dark:text-emerald-400",
        warning:    "border-transparent bg-amber-500/15 text-amber-700 dark:text-amber-400",
        destructive:"border-transparent bg-[var(--color-destructive)]/15 text-[var(--color-destructive)]",
        muted:      "border-transparent bg-[var(--color-muted)] text-[var(--color-muted-fg)]",
      },
    },
    defaultVariants: { variant: "default" },
  },
)

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return <div className={cn(badgeVariants({ variant }), className)} {...props} />
}

export { Badge, badgeVariants }
