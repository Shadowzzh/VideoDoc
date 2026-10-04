import { describe, expect, it } from "vitest"

import { attemptDurationMs, stepDurationMs, taskTiming } from "@/lib/timing"
import type { TaskStep, VideoTask } from "@/types"

const NOW = Date.parse("2026-10-04T12:10:00+08:00")

function step(overrides: Partial<TaskStep> & { key: string }): TaskStep {
  return {
    label: overrides.key,
    status: "completed",
    started_at: null,
    finished_at: null,
    command: null,
    outputs: [],
    error: null,
    attempt_count: 1,
    attempts: [],
    ...overrides,
  }
}

function task(overrides: Partial<VideoTask> = {}): VideoTask {
  return {
    id: "task-1",
    url: "https://example.com/video",
    status: "completed",
    created_at: "2026-10-04T12:00:00+08:00",
    updated_at: "2026-10-04T12:10:00+08:00",
    started_at: "2026-10-04T12:00:00+08:00",
    finished_at: "2026-10-04T12:10:00+08:00",
    error: null,
    metadata: {},
    artifacts: {},
    resume_count: 0,
    can_resume: false,
    resume_from: null,
    progress: { completed: 2, total: 2, percent: 100 },
    steps: [],
    ...overrides,
  }
}

describe("taskTiming", () => {
  it("computes each stage's share of the execution total", () => {
    const value = taskTiming(
      task({
        steps: [
          step({ key: "probe", duration_ms: 5_000 }),
          step({ key: "frames", duration_ms: 815_000 }),
          step({ key: "ocr", duration_ms: 300_000 }),
        ],
      }),
      NOW,
    )

    expect(value.totalMs).toBe(1_120_000)
    // 降序：最贵的在最前。
    expect(value.segments.map((segment) => segment.key)).toEqual([
      "frames",
      "ocr",
      "probe",
    ])
    expect(value.segments[0].percent).toBeCloseTo(72.8, 1)
    expect(value.segments[2].percent).toBeCloseTo(0.45, 2)
    expect(
      value.segments.reduce((sum, segment) => sum + segment.percent, 0),
    ).toBeCloseTo(100, 5)
  })

  it("sorts stages by duration descending", () => {
    const value = taskTiming(
      task({
        steps: [
          step({ key: "probe", duration_ms: 1_000 }),
          step({ key: "download", duration_ms: 900_000 }),
          step({ key: "audio", duration_ms: 2_000 }),
        ],
      }),
      NOW,
    )

    expect(value.segments.map((segment) => segment.key)).toEqual([
      "download",
      "audio",
      "probe",
    ])
  })

  it("skips stages that have not run so they cannot dilute the denominator", () => {
    const value = taskTiming(
      task({
        steps: [
          step({ key: "probe", duration_ms: 60_000 }),
          step({ key: "download", status: "pending", duration_ms: null }),
        ],
      }),
      NOW,
    )

    expect(value.segments.map((segment) => segment.key)).toEqual(["probe"])
    expect(value.segments[0].percent).toBeCloseTo(100, 5)
  })

  it("counts a running stage up to the current moment", () => {
    const running = step({
      key: "frames",
      status: "running",
      started_at: "2026-10-04T12:05:00+08:00",
      duration_ms: null,
    })

    expect(stepDurationMs(running, NOW)).toBe(300_000)
  })

  it("separates wall-clock time from execution time", () => {
    // 墙钟 10 分钟，但阶段执行合计只有 5 分钟：剩下的是排队与重试等待。
    const value = taskTiming(
      task({ steps: [step({ key: "probe", duration_ms: 300_000 })] }),
      NOW,
    )

    expect(value.totalMs).toBe(300_000)
    expect(value.wallMs).toBe(600_000)
    expect(value.gapMs).toBe(300_000)
  })

  it("returns nothing when no stage has run yet", () => {
    const value = taskTiming(
      task({
        status: "queued",
        finished_at: null,
        steps: [step({ key: "probe", status: "pending", duration_ms: null })],
      }),
      NOW,
    )

    expect(value.segments).toEqual([])
    expect(value.totalMs).toBe(0)
  })
})

describe("attemptDurationMs", () => {
  it("measures a finished attempt on its own", () => {
    const value = attemptDurationMs(
      {
        number: 1,
        status: "failed",
        started_at: "2026-10-04T12:00:00+08:00",
        finished_at: "2026-10-04T12:01:18+08:00",
        error: "超时",
        log: "logs/article/attempt-001.log",
      },
      NOW,
    )

    expect(value).toBe(78_000)
  })

  it("counts a running attempt up to the current moment", () => {
    const value = attemptDurationMs(
      {
        number: 2,
        status: "running",
        started_at: "2026-10-04T12:09:00+08:00",
        finished_at: null,
        error: null,
        log: "logs/article/attempt-002.log",
      },
      NOW,
    )

    expect(value).toBe(60_000)
  })

  it("returns null when the attempt never started", () => {
    const value = attemptDurationMs(
      {
        number: 1,
        status: "interrupted",
        started_at: null,
        finished_at: null,
        error: null,
        log: "logs/probe.log",
      },
      NOW,
    )

    expect(value).toBeNull()
  })
})
