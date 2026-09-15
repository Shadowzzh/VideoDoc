import { useEffect, useState } from "react"

export type Theme = "light" | "dark" | "system"

function storedTheme(): Theme {
  const value = window.localStorage.getItem("videodoc-theme")
  if (value === "light" || value === "dark" || value === "system") {
    return value
  }
  return "system"
}

export function useTheme() {
  const [theme, setTheme] = useState<Theme>(storedTheme)

  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)")
    const apply = () => {
      const useDark = theme === "dark" || (theme === "system" && media.matches)
      document.documentElement.classList.toggle("dark", useDark)
      document.documentElement.style.colorScheme = useDark ? "dark" : "light"
    }
    apply()
    media.addEventListener("change", apply)
    window.localStorage.setItem("videodoc-theme", theme)
    return () => media.removeEventListener("change", apply)
  }, [theme])

  return { theme, setTheme }
}
