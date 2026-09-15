import { ArrowRightIcon, LinkIcon, PlusIcon, VideoIcon } from "lucide-react"
import { useState, type FormEvent } from "react"

import { AppShell } from "@/components/app-shell"
import { ErrorState } from "@/components/error-state"
import { StatusBadge } from "@/components/status-badge"
import { TaskActionsMenu } from "@/components/task-actions-menu"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Skeleton } from "@/components/ui/skeleton"
import { createTask, primaryTaskHref, taskHref } from "@/lib/api"
import { formatDate, taskTitle } from "@/lib/format"
import { useTasks } from "@/hooks/use-tasks"

export function HomePage() {
  const { tasks, error, loading } = useTasks()
  const [url, setUrl] = useState("")
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault()
    setSubmitting(true)
    setSubmitError(null)
    try {
      const task = await createTask(url.trim())
      window.location.assign(taskHref(task.id))
    } catch (reason) {
      setSubmitError(reason instanceof Error ? reason.message : "创建任务失败")
      setSubmitting(false)
    }
  }

  return (
    <AppShell>
      <ScrollArea className="h-full">
        <div className="mx-auto w-full max-w-6xl space-y-8 px-5 py-8 md:px-8 md:py-12">
          <div className="space-y-2">
            <p className="text-sm font-medium text-muted-foreground">视频内容工作台</p>
            <h1 className="text-3xl font-semibold tracking-tight md:text-4xl">创建图文文档</h1>
            <p className="max-w-2xl text-muted-foreground">输入视频链接，生成带时间轴、真实关键帧和来源锚点的文章。</p>
          </div>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2"><PlusIcon className="size-5" />新任务</CardTitle>
              <CardDescription>V1 正式支持 YouTube 和 Bilibili，X/Twitter 为 best-effort。</CardDescription>
            </CardHeader>
            <CardContent>
              <form className="flex flex-col gap-3 md:flex-row" onSubmit={handleSubmit}>
                <div className="relative flex-1">
                  <LinkIcon className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
                  <Input
                    type="url"
                    value={url}
                    onChange={(event) => setUrl(event.target.value)}
                    placeholder="https://www.youtube.com/watch?v=..."
                    className="pl-9"
                    required
                    autoFocus
                  />
                </div>
                <Button type="submit" disabled={submitting || !url.trim()}>
                  {submitting ? "创建中…" : "开始处理"}<ArrowRightIcon />
                </Button>
              </form>
              {submitError ? <p className="mt-3 text-sm text-destructive">{submitError}</p> : null}
            </CardContent>
          </Card>

          <section className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-xl font-semibold tracking-tight">最近任务</h2>
                <p className="text-sm text-muted-foreground">查看处理状态和生成结果。</p>
              </div>
              <span className="text-sm text-muted-foreground">{tasks.length} 个任务</span>
            </div>
            {error ? <ErrorState message={error} /> : null}
            {loading ? <TaskGridSkeleton /> : null}
            {!loading && tasks.length === 0 ? (
              <Card className="border-dashed">
                <CardContent className="flex flex-col items-center gap-3 py-10 text-center">
                  <VideoIcon className="size-8 text-muted-foreground" />
                  <div><p className="font-medium">还没有任务</p><p className="text-sm text-muted-foreground">粘贴一个视频链接开始。</p></div>
                </CardContent>
              </Card>
            ) : null}
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {tasks.map((task) => (
                <Card key={task.id} className="group relative h-full gap-4 py-5 transition-colors hover:ring-foreground/25">
                  <a href={primaryTaskHref(task)} className="block pr-10">
                    <CardHeader className="gap-3">
                      <div className="flex items-center justify-between gap-3"><StatusBadge status={task.status} /><span className="text-xs text-muted-foreground">{formatDate(task.created_at)}</span></div>
                      <CardTitle className="line-clamp-2 text-base leading-6">{taskTitle(task)}</CardTitle>
                      <CardDescription>{task.metadata.extractor || "等待识别来源"}</CardDescription>
                    </CardHeader>
                  </a>
                  <div className="absolute right-3 top-3">
                    <TaskActionsMenu
                      task={task}
                      onDeleted={() => window.location.assign("/app/")}
                    />
                  </div>
                </Card>
              ))}
            </div>
          </section>
        </div>
      </ScrollArea>
    </AppShell>
  )
}

function TaskGridSkeleton() {
  return (
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
      {[0, 1, 2].map((item) => <Skeleton key={item} className="h-36 rounded-xl" />)}
    </div>
  )
}
