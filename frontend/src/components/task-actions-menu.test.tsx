import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { TaskActionsMenu } from "@/components/task-actions-menu"
import type { VideoTask } from "@/types"

const task = {
  id: "20260911-120000-1234abcd",
  url: "https://example.com/video",
  status: "completed",
  metadata: { title: "测试任务" },
} as VideoTask

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe("TaskActionsMenu", () => {
  it("previews files and confirms recoverable deletion", async () => {
    const onDeleted = vi.fn()
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith("/deletion-preview")) {
        return new Response(JSON.stringify({
          id: task.id,
          title: "测试任务",
          status: "completed",
          deletable: true,
          total_bytes: 1536,
          total_files: 2,
          groups: {
            video: { label: "视频", bytes: 1024, files: 1 },
            other: { label: "转写、文章与日志", bytes: 512, files: 1 },
          },
        }), { status: 200, headers: { "Content-Type": "application/json" } })
      }
      expect(init?.method).toBe("DELETE")
      expect(init?.body).toBe(JSON.stringify({ confirmation: task.id }))
      return new Response(JSON.stringify({
        id: task.id,
        deleted_at: "2026-09-11T12:30:00+08:00",
        recoverable: true,
      }), { status: 200, headers: { "Content-Type": "application/json" } })
    })
    vi.stubGlobal("fetch", fetchMock)

    render(<TaskActionsMenu task={task} onDeleted={onDeleted} />)

    fireEvent.click(screen.getByRole("button", { name: "测试任务的操作菜单" }))
    fireEvent.click(await screen.findByText("删除任务"))

    expect(await screen.findByText("1.5 KB")).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "移入回收站" }))

    await waitFor(() => expect(onDeleted).toHaveBeenCalledOnce())
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it("disables deletion while a task is running", async () => {
    const runningTask = { ...task, status: "running" } as VideoTask

    render(<TaskActionsMenu task={runningTask} onDeleted={vi.fn()} />)

    fireEvent.click(screen.getByRole("button", { name: "测试任务的操作菜单" }))
    const item = await screen.findByText("运行中不可删除")
    expect(item.closest("[data-disabled]")).toBeInTheDocument()
  })
})
