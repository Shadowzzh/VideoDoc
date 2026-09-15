import { ArrowRightIcon, ChevronRightIcon, ClockIcon, ExternalLinkIcon, FileIcon, RotateCcwIcon, TerminalIcon } from "lucide-react"
import { useState } from "react"

import { AppShell } from "@/components/app-shell"
import { ErrorState } from "@/components/error-state"
import { StatusBadge } from "@/components/status-badge"
import { TaskActionsMenu } from "@/components/task-actions-menu"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Progress } from "@/components/ui/progress"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { Skeleton } from "@/components/ui/skeleton"
import { useTask } from "@/hooks/use-task"
import { downloadHref, resultHref, resumeTask } from "@/lib/api"
import { formatDate, taskTitle } from "@/lib/format"
import type { TaskStep } from "@/types"

export function TaskPage({ taskId }: { taskId: string }) {
  const { task, error, loading, refresh } = useTask(taskId)
  const [selectedStepKey, setSelectedStepKey] = useState<string | null>(null)
  const [resuming, setResuming] = useState(false)
  const [resumeError, setResumeError] = useState<string | null>(null)
  const selectedStep = task?.steps.find((step) => step.key === selectedStepKey) || null
  let taskErrorTitle = "任务失败"
  let taskErrorMessage = task?.error || ""
  if (task?.status === "interrupted") {
    taskErrorTitle = "任务已中断"
  }
  if (task?.error && task.resume_from) {
    taskErrorMessage = `${task.error}\n将从「${task.resume_from.label}」继续。`
  }

  const handleResume = async () => {
    setResuming(true)
    setResumeError(null)
    try {
      await resumeTask(taskId)
      refresh()
    } catch (reason) {
      setResumeError(reason instanceof Error ? reason.message : "恢复任务失败")
    } finally {
      setResuming(false)
    }
  }

  return (
    <AppShell activeTaskId={taskId}>
      <ScrollArea className="h-full">
        <div className="mx-auto w-full max-w-5xl space-y-6 px-5 py-8 md:px-8 md:py-10">
          {loading ? <TaskPageSkeleton /> : null}
          {error ? <ErrorState message={error} /> : null}
          {task ? (
            <>
              <header className="space-y-4">
                <div className="flex flex-col justify-between gap-4 md:flex-row md:items-start">
                  <div className="min-w-0 space-y-2">
                    <div className="flex items-center gap-2"><StatusBadge status={task.status} /><span className="font-mono text-xs text-muted-foreground">{task.id}</span></div>
                    <h1 className="text-2xl font-semibold tracking-tight md:text-3xl">{taskTitle(task)}</h1>
                    <a className="inline-flex max-w-full items-center gap-1 truncate text-sm text-muted-foreground hover:text-foreground" href={task.url} target="_blank" rel="noreferrer">{task.url}<ExternalLinkIcon className="size-3.5 shrink-0" /></a>
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    {task.status === "completed" ? (
                      <Button nativeButton={false} render={<a href={resultHref(task.id)} />}>打开文章<ArrowRightIcon /></Button>
                    ) : null}
                    {task.can_resume && task.resume_from ? (
                      <Button disabled={resuming} onClick={() => void handleResume()}>
                        <RotateCcwIcon />
                        {resuming ? "正在恢复" : "重试当前阶段"}
                      </Button>
                    ) : null}
                    <TaskActionsMenu
                      task={task}
                      onDeleted={() => window.location.assign("/app/")}
                    />
                  </div>
                </div>
                <div className="space-y-2">
                  <div className="flex items-center justify-between text-sm"><span className="text-muted-foreground">{task.progress.completed}/{task.progress.total} 个步骤</span><strong>{task.progress.percent}%</strong></div>
                  <Progress value={task.progress.percent} />
                </div>
              </header>

              {task.error ? (
                <ErrorState
                  title={taskErrorTitle}
                  message={taskErrorMessage}
                />
              ) : null}
              {resumeError ? <ErrorState title="恢复失败" message={resumeError} /> : null}

              <section className="space-y-3">
                <div><h2 className="text-lg font-semibold">处理流水线</h2><p className="text-sm text-muted-foreground">点击步骤查看命令、产物和完整日志。</p></div>
                <div className="space-y-2">
                  {task.steps.map((step, index) => (
                    <button key={step.key} type="button" onClick={() => setSelectedStepKey(step.key)} className="block w-full text-left">
                      <Card className="gap-0 py-0 transition-colors hover:bg-accent/50">
                        <CardContent className="flex items-center gap-4 px-4 py-4 md:px-5">
                          <span className="flex size-8 shrink-0 items-center justify-center rounded-full border bg-background font-mono text-xs text-muted-foreground">{String(index + 1).padStart(2, "0")}</span>
                          <div className="min-w-0 flex-1"><p className="font-medium">{step.label}</p><p className="mt-0.5 truncate text-xs text-muted-foreground">{step.error || step.command || "等待执行"}</p></div>
                          <StatusBadge status={step.status} />
                          <ChevronRightIcon className="size-4 text-muted-foreground" />
                        </CardContent>
                      </Card>
                    </button>
                  ))}
                </div>
              </section>

              {task.status === "completed" ? (
                <Card>
                  <CardHeader><CardTitle className="text-base">交付产物</CardTitle><CardDescription>打开交互式文章，或下载结构化结果。</CardDescription></CardHeader>
                  <CardContent className="flex flex-wrap gap-2">
                    <Button nativeButton={false} render={<a href={resultHref(task.id)} />}>交互式文章</Button>
                    <Button nativeButton={false} variant="outline" render={<a href={downloadHref(task.id, "article.md")} />}>Markdown</Button>
                    <Button nativeButton={false} variant="outline" render={<a href={downloadHref(task.id, "result.json")} />}>结果 JSON</Button>
                  </CardContent>
                </Card>
              ) : null}
            </>
          ) : null}
        </div>
      </ScrollArea>

      <Sheet open={selectedStep !== null} onOpenChange={(open) => { if (!open) setSelectedStepKey(null) }}>
        <SheetContent className="w-full p-0 sm:max-w-2xl">
          {selectedStep ? <StepDetails step={selectedStep} /> : null}
        </SheetContent>
      </Sheet>
    </AppShell>
  )
}

function StepDetails({ step }: { step: TaskStep }) {
  return (
    <div className="flex h-full min-h-0 flex-col">
      <SheetHeader className="border-b pr-12"><div className="flex items-center gap-2"><StatusBadge status={step.status} /><span className="font-mono text-xs text-muted-foreground">{step.key}</span></div><SheetTitle>{step.label}</SheetTitle><SheetDescription>该步骤的执行时间、命令、产物和日志。</SheetDescription></SheetHeader>
      <ScrollArea className="min-h-0 flex-1">
        <div className="space-y-6 p-5">
          <section className="space-y-2"><h3 className="flex items-center gap-2 text-sm font-medium"><ClockIcon className="size-4" />执行时间</h3><p className="text-sm text-muted-foreground">{formatDate(step.started_at)} → {formatDate(step.finished_at)}</p></section>
          <section className="space-y-2">
            <h3 className="text-sm font-medium">执行记录</h3>
            {step.attempts.length ? (
              <div className="space-y-2">
                {step.attempts.map((attempt) => (
                  <div key={attempt.number} className="flex items-start justify-between gap-4 rounded-lg border px-3 py-2 text-sm">
                    <div className="min-w-0">
                      <p className="font-medium">第 {attempt.number} 次尝试</p>
                      <p className="mt-0.5 text-xs text-muted-foreground">{formatDate(attempt.started_at)} → {formatDate(attempt.finished_at)}</p>
                      {attempt.error ? <p className="mt-1 text-xs text-destructive">{attempt.error}</p> : null}
                    </div>
                    <StatusBadge status={attempt.status} />
                  </div>
                ))}
              </div>
            ) : <p className="text-sm text-muted-foreground">尚未执行</p>}
          </section>
          <section className="space-y-2"><h3 className="flex items-center gap-2 text-sm font-medium"><TerminalIcon className="size-4" />命令</h3><pre className="overflow-x-auto rounded-lg border bg-zinc-950 p-4 font-mono text-xs leading-5 text-zinc-100 whitespace-pre-wrap">{step.command || "尚未生成命令"}</pre></section>
          <section className="space-y-2"><h3 className="flex items-center gap-2 text-sm font-medium"><FileIcon className="size-4" />产物</h3>{step.outputs.length ? <ul className="space-y-1 font-mono text-xs text-muted-foreground">{step.outputs.map((output) => <li key={output}>{output}</li>)}</ul> : <p className="text-sm text-muted-foreground">暂无产物</p>}</section>
          <section className="space-y-2"><h3 className="text-sm font-medium">日志</h3><pre className="min-h-48 overflow-x-auto rounded-lg border bg-zinc-950 p-4 font-mono text-xs leading-5 text-zinc-100 whitespace-pre-wrap">{step.log_tail || step.error || "暂无日志"}</pre></section>
        </div>
      </ScrollArea>
    </div>
  )
}

function TaskPageSkeleton() {
  return <div className="space-y-5"><Skeleton className="h-10 w-2/3" /><Skeleton className="h-2 w-full" />{[0, 1, 2, 3].map((item) => <Skeleton key={item} className="h-16 w-full" />)}</div>
}
