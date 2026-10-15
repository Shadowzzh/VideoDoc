import { ArrowRightIcon, ChevronRightIcon, CircleStopIcon, ClockIcon, ExternalLinkIcon, FileIcon, RotateCcwIcon, TerminalIcon, TimerIcon } from "lucide-react"
import { useState } from "react"

import { AppShell } from "@/components/app-shell"
import { CancelTaskDialog } from "@/components/cancel-task-dialog"
import { ErrorState } from "@/components/error-state"
import { StatusBadge } from "@/components/status-badge"
import { TaskActionsMenu } from "@/components/task-actions-menu"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Progress } from "@/components/ui/progress"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { Skeleton } from "@/components/ui/skeleton"
import { useNow } from "@/hooks/use-now"
import { useTask } from "@/hooks/use-task"
import { downloadHref, resultHref, resumeTask } from "@/lib/api"
import { formatBytes, formatDate, formatDurationMilliseconds, formatPercent, taskTitle } from "@/lib/format"
import { stepDurationMs, attemptDurationMs, taskTiming } from "@/lib/timing"
import type { TaskStep, VideoTask } from "@/types"

export function TaskPage({ taskId }: { taskId: string }) {
  const { task, error, loading, refresh } = useTask(taskId)
  const [selectedStepKey, setSelectedStepKey] = useState<string | null>(null)
  const [resuming, setResuming] = useState(false)
  const [resumeError, setResumeError] = useState<string | null>(null)
  const [cancelOpen, setCancelOpen] = useState(false)
  const selectedStep = task?.steps.find((step) => step.key === selectedStepKey) || null
  // 运行中按秒重算已耗时；任务结束后停掉定时器，避免页面白页重渲染。
  const now = useNow(task?.status === "running" || task?.status === "queued")
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
                    {task.status === "running" || task.status === "queued" ? (
                      <Button
                        variant="outline"
                        disabled={Boolean(task.cancel_requested_at)}
                        onClick={() => setCancelOpen(true)}
                      >
                        <CircleStopIcon />
                        {task.cancel_requested_at ? "正在终止…" : "终止任务"}
                      </Button>
                    ) : null}
                    <TaskActionsMenu
                      task={task}
                      onDeleted={() => window.location.assign("/app/")}
                      onChanged={refresh}
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
              {task.status === "cancelled" ? (
                <ErrorState
                  tone="neutral"
                  icon={<CircleStopIcon className="size-4" />}
                  title="任务已取消"
                  message={
                    task.resume_from
                      ? `已完成的阶段产物保留，可从「${task.resume_from.label}」继续。`
                      : "已完成的阶段产物保留。"
                  }
                />
              ) : null}

              <section className="space-y-3">
                <div><h2 className="text-lg font-semibold">处理流水线</h2><p className="text-sm text-muted-foreground">点击步骤查看命令、产物和完整日志。</p></div>
                <div className="space-y-2">
                  {task.steps.map((step, index) => (
                    <button key={step.key} type="button" onClick={() => setSelectedStepKey(step.key)} className="block w-full text-left">
                      <Card className="gap-0 py-0 transition-colors hover:bg-accent/50">
                        <CardContent className="flex items-center gap-4 px-4 py-4 md:px-5">
                          <span className="flex size-8 shrink-0 items-center justify-center rounded-full border bg-background font-mono text-xs text-muted-foreground">{String(index + 1).padStart(2, "0")}</span>
                          <div className="min-w-0 flex-1"><p className="font-medium">{step.label}</p><p className="mt-0.5 truncate text-xs text-muted-foreground">{step.error || step.command || "等待执行"}</p></div>
                          <StepDuration step={step} now={now} />
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

              <TimingOverview task={task} now={now} />
            </>
          ) : null}
        </div>
      </ScrollArea>

      <Sheet open={selectedStep !== null} onOpenChange={(open) => { if (!open) setSelectedStepKey(null) }}>
        <SheetContent className="w-full p-0 sm:max-w-2xl">
          {selectedStep ? <StepDetails step={selectedStep} now={now} /> : null}
        </SheetContent>
      </Sheet>

      {task ? (
        <CancelTaskDialog
          task={task}
          open={cancelOpen}
          onOpenChange={setCancelOpen}
          onCancelled={refresh}
        />
      ) : null}
    </AppShell>
  )
}

function StepDetails({ step, now }: { step: TaskStep; now: number }) {
  const duration = stepDurationMs(step, now)
  const breakdown = buildBreakdown(step)
  const derived = Object.entries(step.metrics?.derived ?? {})
  return (
    <div className="flex h-full min-h-0 flex-col">
      <SheetHeader className="border-b pr-12"><div className="flex items-center gap-2"><StatusBadge status={step.status} /><span className="font-mono text-xs text-muted-foreground">{step.key}</span></div><SheetTitle>{step.label}</SheetTitle><SheetDescription>该步骤的执行时间、各段耗时构成、归一化指标、命令、产物和日志。</SheetDescription></SheetHeader>
      <ScrollArea className="min-h-0 flex-1">
        <div className="space-y-6 p-5">
          <section className="space-y-2"><h3 className="flex items-center gap-2 text-sm font-medium"><ClockIcon className="size-4" />执行时间</h3><p className="text-sm text-muted-foreground">{formatDate(step.started_at)} → {formatDate(step.finished_at)} · 耗时 {formatDurationMilliseconds(duration)}</p></section>
          {breakdown.length ? (
            <section className="space-y-2">
              <h3 className="flex items-center gap-2 text-sm font-medium"><TimerIcon className="size-4" />耗时构成</h3>
              <p className="text-xs text-muted-foreground">按耗时降序，直接指向最耗时的那一段。</p>
              <div className="space-y-1.5">
                {breakdown.map((item) => (
                  <div key={item.key} className="flex items-baseline justify-between gap-4 rounded-lg border px-3 py-2 text-sm">
                    <div className="min-w-0"><p className="truncate font-medium">{item.label}</p>{item.detail ? <p className="mt-0.5 text-xs text-muted-foreground">{item.detail}</p> : null}</div>
                    <span className="shrink-0 font-mono text-xs text-muted-foreground">{formatDurationMilliseconds(item.duration)}</span>
                  </div>
                ))}
              </div>
            </section>
          ) : null}
          {derived.length ? (
            <section className="space-y-2">
              <h3 className="text-sm font-medium">归一化指标</h3>
              <p className="text-xs text-muted-foreground">把耗时除以输入规模，跨任务、跨视频长度才可比。</p>
              <dl className="grid grid-cols-1 gap-x-6 gap-y-1.5 text-sm sm:grid-cols-2">
                {derived.map(([key, value]) => (
                  <div key={key} className="flex items-baseline justify-between gap-3 border-b border-dashed pb-1">
                    <dt className="text-muted-foreground">{DERIVED_LABELS[key] ?? key}</dt>
                    <dd className="shrink-0 font-mono text-xs">{formatDerivedValue(key, value)}</dd>
                  </div>
                ))}
              </dl>
            </section>
          ) : null}
          <section className="space-y-2">
            <h3 className="text-sm font-medium">执行记录</h3>
            {step.attempts.length ? (
              <div className="space-y-2">
                {step.attempts.map((attempt) => (
                  <div key={attempt.number} className="flex items-start justify-between gap-4 rounded-lg border px-3 py-2 text-sm">
                    <div className="min-w-0">
                      <p className="font-medium">第 {attempt.number} 次尝试</p>
                      <p className="mt-0.5 text-xs text-muted-foreground">{formatDate(attempt.started_at)} → {formatDate(attempt.finished_at)} · 耗时 {formatDurationMilliseconds(attemptDurationMs(attempt, now))}</p>
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

/**
 * 阶段配色：同明度、同饱和、只变色相的柔色，并把色相**打散**排列。
 *
 * 两组反馈合起来指向的解法：全饱和的 Tailwind 色板（sky-500/violet-500…）在纯中性灰主题里
 * 显得很跳；而纯灰度又堆在 1-2 像素宽的小段和 6 像素圆点上分不出来。所以固定明度 0.68
 * 与饱和 0.10（柔而不脏），只让色相变；色相数组刻意让相邻两项相隔 100° 以上，
 * 保证排序后上下两个阶段不会撞色。
 */
const TIMING_HUES = [250, 30, 160, 310, 85, 200, 340, 130, 15, 275]

function timingTone(index: number): string {
  return `oklch(0.68 0.10 ${TIMING_HUES[index % TIMING_HUES.length]})`
}

/**
 * 耗时分布卡片。
 *
 * 颜色只负责「区分是哪一段」，占比一律用长度编码（堆叠条宽度 + 行背景填充），
 * 因为长度是连续的，而颜色在小尺寸上会退化。
 */
function TimingOverview({ task, now }: { task: VideoTask; now: number }) {
  const timing = taskTiming(task, now)
  if (!timing.segments.length) {
    return null
  }
  const showGap = timing.gapMs > 1000
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">耗时分布</CardTitle>
        <CardDescription>
          各阶段执行合计 {formatDurationMilliseconds(timing.totalMs)}
          {showGap ? `，另有 ${formatDurationMilliseconds(timing.gapMs)} 在排队或等待重试` : null}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex h-1.5 w-full gap-px overflow-hidden rounded-md bg-muted">
          {timing.segments.map((segment, index) => (
            <div
              key={segment.key}
              style={{ width: `${segment.percent}%`, minWidth: 2, backgroundColor: timingTone(index) }}
              title={`${segment.label} · ${formatDurationMilliseconds(segment.ms)} · ${formatPercent(segment.percent)}`}
            />
          ))}
        </div>
        <ul className="space-y-0.5">
          {timing.segments.map((segment, index) => (
            <li key={segment.key} className="relative flex items-center gap-3 overflow-hidden rounded-md px-2 py-1 text-sm">
              {/* 行背景只做长度编码（中性色）；用 primary 透明度而不是 bg-muted：
                  muted 在浅色下是 0.97、贴在白卡片上几乎看不见，深色下反而清楚。 */}
              <div className="absolute inset-y-0 left-0 bg-primary/10" style={{ width: `${segment.percent}%` }} aria-hidden />
              <span className="relative size-2 shrink-0 rounded-full" style={{ backgroundColor: timingTone(index) }} />
              <span className="relative min-w-0 flex-1 truncate">{segment.label}</span>
              <span className="relative shrink-0 font-mono text-xs tabular-nums text-muted-foreground">{formatDurationMilliseconds(segment.ms)}</span>
              <span className="relative w-12 shrink-0 text-right font-mono text-xs tabular-nums text-muted-foreground">{formatPercent(segment.percent)}</span>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  )
}

/** 运行中阶段用当前时间减开始时间，已结束阶段用后端算好的值。 */
function StepDuration({ step, now }: { step: TaskStep; now: number }) {
  const value = stepDurationMs(step, now)
  if (value === null) {
    return null
  }
  const running = step.status === "running"
  // 心跳点：绿点脉动表示子进程还活着；运行中却没有心跳时保持灰色，不假装正常。
  return (
    <span className="flex shrink-0 items-center gap-1.5 font-mono text-xs text-muted-foreground">
      {running ? <span className={`size-1.5 rounded-full ${step.heartbeat ? "animate-pulse bg-emerald-500" : "bg-muted-foreground/50"}`} /> : null}
      {formatDurationMilliseconds(value)}
    </span>
  )
}

interface BreakdownItem {
  key: string
  label: string
  detail: string
  duration: number
}

/** 把阶段内的外部命令和 LLM 调用铺平并按耗时降序：先看最贵的那一段。 */
function buildBreakdown(step: TaskStep): BreakdownItem[] {
  const items: BreakdownItem[] = []
  const commands = step.metrics?.command ?? []
  const calls = step.metrics?.llm ?? []
  commands.forEach((command, index) => {
    items.push({
      key: `command-${index}`,
      label: command.program || "外部命令",
      detail: command.exit_code === 0 || command.exit_code === null ? "外部命令" : `退出码 ${command.exit_code}`,
      duration: command.duration_ms,
    })
  })
  calls.forEach((call, index) => {
    const detail = [call.model]
    if (call.total_tokens) {
      detail.push(`${call.total_tokens} tokens`)
    }
    if (call.output_tokens_per_second) {
      detail.push(`${call.output_tokens_per_second} tok/s 生成`)
    } else if (call.tokens_per_second) {
      detail.push(`${call.tokens_per_second} tok/s`)
    }
    if (call.retries) {
      detail.push(`重试 ${call.retries} 次 · 退避 ${call.backoff_ms} ms`)
    }
    items.push({
      key: `llm-${index}`,
      label: call.label ? `LLM · ${call.label}` : "LLM 调用",
      detail: detail.join(" · "),
      duration: call.duration_ms,
    })
  })
  return items.sort((left, right) => right.duration - left.duration)
}

const DERIVED_LABELS: Record<string, string> = {
  bytes: "视频大小",
  megabytes_per_second: "下载速率",
  seconds: "阶段耗时",
  frames: "抽帧数",
  source_codec: "源编码",
  source_height: "源高度",
  source_fps: "源帧率",
  video_seconds: "视频时长",
  seconds_per_video_minute: "秒 / 视频分钟",
  segments: "转写片段数",
  audio_seconds: "音频时长",
  realtime_factor: "实时倍率",
  images: "配图数",
  seconds_per_image: "秒 / 张",
  local_images: "本地识别张数",
  local_ms_total: "本地识别总耗时",
  remote_images: "云端识别张数",
  remote_ms_total: "云端调用总耗时",
  remote_ms_median: "云端单张中位",
  wait_ms_total: "限流等待合计",
  providers: "视觉引擎",
}

function formatDerivedValue(key: string, value: string | number): string {
  if (typeof value === "string") {
    return value
  }
  if (key === "bytes" || key === "filesize") {
    return formatBytes(value)
  }
  if (key.endsWith("_ms") || key.endsWith("_ms_total") || key.endsWith("_ms_median")) {
    return formatDurationMilliseconds(value)
  }
  if (key === "realtime_factor") {
    return `${value}×`
  }
  if (key === "megabytes_per_second") {
    return `${value} MB/s`
  }
  if (key === "tokens_per_second") {
    return `${value} tok/s`
  }
  if (key === "seconds" || key === "seconds_per_image" || key === "seconds_per_video_minute" || key === "audio_seconds" || key === "video_seconds") {
    return `${value} s`
  }
  return String(value)
}
