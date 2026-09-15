import { MonitorIcon, MoonIcon, SunIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { type Theme } from "@/hooks/use-theme"

const sequence: Theme[] = ["system", "light", "dark"]

export function ThemeToggle({ theme, onChange }: { theme: Theme; onChange: (theme: Theme) => void }) {
  const index = sequence.indexOf(theme)
  const nextTheme = sequence[(index + 1) % sequence.length]
  let Icon = MonitorIcon
  if (theme === "light") {
    Icon = SunIcon
  } else if (theme === "dark") {
    Icon = MoonIcon
  }

  return (
    <Tooltip>
      <TooltipTrigger render={<Button variant="ghost" size="icon" aria-label="切换主题" onClick={() => onChange(nextTheme)} />}>
        <Icon />
      </TooltipTrigger>
      <TooltipContent>主题：{theme}</TooltipContent>
    </Tooltip>
  )
}
