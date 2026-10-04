import type { TaskAttempt, TaskStep, VideoTask } from "@/types"

/**
 * 运行中阶段用当前时间减开始时间，已结束阶段用后端算好的值。
 *
 * 后端只在阶段结束、或中断/失败时才写 `finished_at`，所以运行中的阶段必须由前端
 * 自己按秒推。
 */
export function stepDurationMs(step: TaskStep, now: number): number | null {
  if (step.status === "running" && step.started_at) {
    return Math.max(0, now - new Date(step.started_at).getTime())
  }
  return step.duration_ms ?? null
}

/**
 * 单次尝试的耗时。
 *
 * 阶段耗时只反映「最后一次尝试」（每次 `start_attempt` 都会覆盖 step.started_at），
 * 所以失败那几次白花的时间只能从 attempts 里逐条看。
 */
export function attemptDurationMs(attempt: TaskAttempt, now: number): number | null {
  if (!attempt.started_at) {
    return null
  }
  const started = new Date(attempt.started_at).getTime()
  if (Number.isNaN(started)) {
    return null
  }
  if (attempt.finished_at) {
    const finished = new Date(attempt.finished_at).getTime()
    return Number.isNaN(finished) ? null : Math.max(0, finished - started)
  }
  if (attempt.status === "running") {
    return Math.max(0, now - started)
  }
  return null
}

export interface TimingSegment {
  key: string
  label: string
  ms: number
  /** 占「执行合计」的百分比（0-100）。 */
  percent: number
}

export interface TaskTiming {
  /** 各阶段执行耗时之和：这才是真正可优化的部分。 */
  totalMs: number
  /** 墙钟时间：从创建到结束（运行中算到当前），含排队与重试等待。 */
  wallMs: number | null
  /** 墙钟与执行合计的差：排队、重试等待、服务重启间隔。 */
  gapMs: number
  segments: TimingSegment[]
}

/**
 * 汇总任务的耗时分布。
 *
 * 为什么同时给 `totalMs` 和 `wallMs`：各阶段耗时相加只覆盖真正在跑的代码，而墙钟
 * 时间含排队和重试等待。两者差得多，说明瓶颈可能根本不在流水线本身。
 *
 * 同时给两者是因为只看墙钟时间会误导优化方向：比如「article 阶段 600 秒」，其中
 * 可能大半是重试前的 sleep，而不是模型在算。
 */
export function taskTiming(task: VideoTask, now: number): TaskTiming {
  const segments: TimingSegment[] = []
  let totalMs = 0

  // 保持流水线顺序（不按耗时排序）：堆叠条与下面的阶段卡片一一对应才好读。
  for (const step of task.steps) {
    const ms = stepDurationMs(step, now)
    if (ms === null || ms <= 0) {
      continue
    }
    totalMs += ms
    segments.push({ key: step.key, label: step.label, ms, percent: 0 })
  }

  // 按耗时降序：先看最贵的，与抽屉里的「耗时构成」保持同一读法。
  segments.sort((left, right) => right.ms - left.ms)

  for (const segment of segments) {
    segment.percent = totalMs > 0 ? (segment.ms / totalMs) * 100 : 0
  }

  const wallMs = taskWallMs(task, now)
  return {
    totalMs,
    wallMs,
    gapMs: wallMs === null ? 0 : Math.max(0, wallMs - totalMs),
    segments,
  }
}

function taskWallMs(task: VideoTask, now: number): number | null {
  if (!task.created_at) {
    return null
  }
  const started = new Date(task.created_at).getTime()
  if (Number.isNaN(started)) {
    return null
  }
  if (task.finished_at) {
    const finished = new Date(task.finished_at).getTime()
    return Number.isNaN(finished) ? null : Math.max(0, finished - started)
  }
  // 排队中或运行中：墙钟还在走，算到当前时刻。
  if (task.status === "queued" || task.status === "running") {
    return Math.max(0, now - started)
  }
  return null
}
