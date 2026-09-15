import { describe, expect, it } from "vitest"

import { primaryTaskHref } from "@/lib/api"
import { formatBytes, formatSeconds, resultTitle, taskTitle } from "@/lib/format"
import type { VideoResult, VideoTask } from "@/types"

describe("format helpers", () => {
  it("formats video time", () => {
    expect(formatSeconds(65)).toBe("01:05")
    expect(formatSeconds(3661)).toBe("01:01:01")
  })

  it("formats task storage size", () => {
    expect(formatBytes(800)).toBe("800 B")
    expect(formatBytes(1536)).toBe("1.5 KB")
    expect(formatBytes(25 * 1024 * 1024)).toBe("25 MB")
  })

  it("prefers metadata title", () => {
    const task = { metadata: { title: "视频标题" }, url: "https://example.com" } as VideoTask
    expect(taskTitle(task)).toBe("视频标题")
  })

  it("prefers the generated Chinese article title", () => {
    const task = {
      article_title: "AI 中文文章标题",
      metadata: { title: "Original English Video Title" },
      url: "https://example.com",
    } as VideoTask
    const result = {
      article_title: "AI 中文文章标题",
      outline: { title: "中文大纲标题" },
      metadata: { title: "Original English Video Title" },
    } as VideoResult

    expect(taskTitle(task)).toBe("AI 中文文章标题")
    expect(resultTitle(result)).toBe("AI 中文文章标题")
  })

  it("uses the article as the primary destination for completed tasks", () => {
    const completed = { id: "task-1", status: "completed" } as VideoTask
    const running = { id: "task-2", status: "running" } as VideoTask

    expect(primaryTaskHref(completed)).toBe("/app/tasks/task-1/result")
    expect(primaryTaskHref(running)).toBe("/app/tasks/task-2")
  })
})
