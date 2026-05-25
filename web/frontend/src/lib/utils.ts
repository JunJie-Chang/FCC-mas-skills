import { type ClassValue, clsx } from "clsx"
import { twMerge } from "tailwind-merge"

/**
 * Standard shadcn cn() — merge conditional + Tailwind classes, then
 * dedupe conflicting Tailwind utilities (e.g. `p-2 p-4` → `p-4`).
 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}
