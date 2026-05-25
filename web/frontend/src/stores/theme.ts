import { create } from "zustand"
import { persist } from "zustand/middleware"

/**
 * Theme persistence — light is the default because IB docs go to clients
 * sometimes (light mode renders properly when printed / screenshotted).
 * Dark is the secondary, opt-in.
 *
 * Persisted to localStorage so a refresh doesn't flash.
 */
type Theme = "light" | "dark"

interface ThemeState {
  theme: Theme
  setTheme: (t: Theme) => void
  toggle: () => void
}

export const useTheme = create<ThemeState>()(
  persist(
    (set, get) => ({
      theme: "light",
      setTheme: (t) => set({ theme: t }),
      toggle: () => set({ theme: get().theme === "light" ? "dark" : "light" }),
    }),
    { name: "fcc-theme" },
  ),
)

/** Reflect the store's theme onto the <html> element so Tailwind's
 *  .dark variant kicks in. Call once at app boot. */
export function bindThemeToDom() {
  const apply = (t: Theme) => {
    const html = document.documentElement
    if (t === "dark") html.classList.add("dark")
    else html.classList.remove("dark")
  }
  apply(useTheme.getState().theme)
  useTheme.subscribe((state) => apply(state.theme))
}
