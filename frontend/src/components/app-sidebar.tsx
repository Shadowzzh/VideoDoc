import { ListVideoIcon, PlusIcon } from "lucide-react"

import { StatusBadge } from "@/components/status-badge"
import { Button } from "@/components/ui/button"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Separator } from "@/components/ui/separator"
import { Skeleton } from "@/components/ui/skeleton"
import { formatDate, taskTitle } from "@/lib/format"
import { primaryTaskHref } from "@/lib/api"
import type { VideoTask } from "@/types"

interface AppSidebarProps {
  tasks: VideoTask[]
  loading: boolean
  activeTaskId?: string
  onNavigate?: () => void
}

export function AppSidebar({ tasks, loading, activeTaskId, onNavigate }: AppSidebarProps) {
  const iconUrl = `${import.meta.env.BASE_URL}brand/videodoc-icon.png`
  return (
    <aside className="flex h-full min-h-0 w-full flex-col bg-sidebar text-sidebar-foreground">
      <div className="flex h-14 items-center gap-2 px-4">
        <div className="flex size-8 items-center justify-center">
          <img src={iconUrl} alt="" className="size-8 object-contain dark:invert" />
        </div>
        <div className="min-w-0">
          <a href="/app/" className="block font-semibold tracking-tight" onClick={onNavigate}>VideoDoc</a>
          <p className="truncate text-[11px] text-muted-foreground">视频图文工作台</p>
        </div>
      </div>
      <Separator />
      <div className="p-3">
        <Button nativeButton={false} render={<a href="/app/" onClick={onNavigate} />} className="w-full justify-start">
          <PlusIcon />创建任务
        </Button>
      </div>
      <div className="flex items-center justify-between px-4 py-2 text-xs font-medium text-muted-foreground">
        <span>最近任务</span>
        <span>{tasks.length}</span>
      </div>
      <ScrollArea className="min-h-0 flex-1 px-2 pb-3">
        <div className="space-y-1">
          {loading ? <SidebarSkeleton /> : null}
          {!loading && tasks.length === 0 ? (
            <div className="px-3 py-8 text-center text-xs text-muted-foreground">还没有任务</div>
          ) : null}
          {tasks.map((task) => {
            const active = task.id === activeTaskId
            return (
              <a
                key={task.id}
                href={primaryTaskHref(task)}
                onClick={onNavigate}
                className={active ? "block rounded-lg bg-sidebar-accent px-3 py-2.5" : "block rounded-lg px-3 py-2.5 hover:bg-sidebar-accent/70"}
              >
                <div className="mb-1.5 flex items-center justify-between gap-2">
                  <StatusBadge status={task.status} />
                  <span className="text-[10px] text-muted-foreground">{formatDate(task.created_at)}</span>
                </div>
                <p className="line-clamp-2 text-sm font-medium leading-5">{taskTitle(task)}</p>
                <div className="mt-1 flex items-center gap-1 text-[11px] text-muted-foreground">
                  <ListVideoIcon className="size-3" />
                  <span className="truncate">{task.metadata.extractor || "等待识别"}</span>
                </div>
              </a>
            )
          })}
        </div>
      </ScrollArea>
    </aside>
  )
}

function SidebarSkeleton() {
  return (
    <div className="space-y-3 px-2 py-2">
      {[0, 1, 2].map((item) => (
        <div key={item} className="space-y-2 rounded-lg border p-3">
          <Skeleton className="h-4 w-16" />
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-3 w-2/3" />
        </div>
      ))}
    </div>
  )
}
