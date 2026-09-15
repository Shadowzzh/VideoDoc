import { MenuIcon, PanelLeftCloseIcon, PanelLeftOpenIcon } from "lucide-react"
import { useState, type ReactNode } from "react"

import { AppSidebar } from "@/components/app-sidebar"
import { ThemeToggle } from "@/components/theme-toggle"
import { Button } from "@/components/ui/button"
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { useMediaQuery } from "@/hooks/use-media-query"
import { useTheme } from "@/hooks/use-theme"
import { useTasks } from "@/hooks/use-tasks"

interface AppShellProps {
  children?: ReactNode
  activeTaskId?: string
  renderSidebar?: (onNavigate?: () => void) => ReactNode
  sidebarLabel?: string
}

export function AppShell({ children, activeTaskId, renderSidebar, sidebarLabel = "任务导航" }: AppShellProps) {
  const desktop = useMediaQuery("(min-width: 1024px)")
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false)
  const { tasks, loading } = useTasks()
  const { theme, setTheme } = useTheme()

  const showDesktopSidebar = desktop && sidebarOpen
  const desktopSidebar = renderSidebar
    ? renderSidebar()
    : <AppSidebar tasks={tasks} loading={loading} activeTaskId={activeTaskId} />
  const mobileSidebar = renderSidebar
    ? renderSidebar(() => setMobileSidebarOpen(false))
    : (
      <AppSidebar
        tasks={tasks}
        loading={loading}
        activeTaskId={activeTaskId}
        onNavigate={() => setMobileSidebarOpen(false)}
      />
    )

  return (
    <div className="flex h-dvh overflow-hidden bg-background">
      {showDesktopSidebar ? (
        <div className="w-64 shrink-0 border-r border-sidebar-border">
          {desktopSidebar}
        </div>
      ) : null}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center justify-between border-b bg-background/95 px-3 backdrop-blur md:px-5">
          <div className="flex items-center gap-1">
            {desktop ? (
              <Tooltip>
                <TooltipTrigger render={<Button variant="ghost" size="icon" onClick={() => setSidebarOpen((value) => !value)} />}>
                  {sidebarOpen ? <PanelLeftCloseIcon /> : <PanelLeftOpenIcon />}
                  <span className="sr-only">切换{sidebarLabel}</span>
                </TooltipTrigger>
                <TooltipContent>切换{sidebarLabel}</TooltipContent>
              </Tooltip>
            ) : (
              <Button variant="ghost" size="icon" onClick={() => setMobileSidebarOpen(true)}>
                <MenuIcon />
                <span className="sr-only">打开{sidebarLabel}</span>
              </Button>
            )}
            {!showDesktopSidebar ? <span className="ml-2 font-semibold">VideoDoc</span> : null}
          </div>
          <ThemeToggle theme={theme} onChange={setTheme} />
        </header>
        <main className="min-h-0 flex-1 overflow-hidden">{children}</main>
      </div>

      <Sheet open={mobileSidebarOpen} onOpenChange={setMobileSidebarOpen}>
        <SheetContent side="left" className="w-[86vw] max-w-72 p-0">
          <SheetTitle className="sr-only">{sidebarLabel}</SheetTitle>
          {mobileSidebar}
        </SheetContent>
      </Sheet>
    </div>
  )
}
