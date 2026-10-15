import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react"
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

  it("allows deleting a queued task", async () => {
    const onDeleted = vi.fn()
    const queuedTask = { ...task, status: "queued" } as VideoTask
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith("/deletion-preview")) {
        // 等待中的任务还没产物，预览里只有几个 0 字节分组。
        return new Response(JSON.stringify({
          id: task.id,
          title: "测试任务",
          status: "queued",
          deletable: true,
          total_bytes: 0,
          total_files: 0,
          groups: {
            video: { label: "视频", bytes: 0, files: 0 },
            audio: { label: "音频", bytes: 0, files: 0 },
          },
        }), { status: 200, headers: { "Content-Type": "application/json" } })
      }
      expect(init?.method).toBe("DELETE")
      return new Response(JSON.stringify({
        id: task.id,
        deleted_at: "2026-10-05T15:40:00+08:00",
        recoverable: true,
      }), { status: 200, headers: { "Content-Type": "application/json" } })
    })
    vi.stubGlobal("fetch", fetchMock)

    render(<TaskActionsMenu task={queuedTask} onDeleted={onDeleted} />)

    fireEvent.click(screen.getByRole("button", { name: "测试任务的操作菜单" }))
    const item = await screen.findByText("删除任务")
    expect(item.closest("[data-disabled]")).toBeNull()
    fireEvent.click(item)
    fireEvent.click(await screen.findByRole("button", { name: "移入回收站" }))

    await waitFor(() => expect(onDeleted).toHaveBeenCalledOnce())
  })

  it("disables deletion while a task is running", async () => {
    const runningTask = { ...task, status: "running" } as VideoTask

    render(<TaskActionsMenu task={runningTask} onDeleted={vi.fn()} />)

    fireEvent.click(screen.getByRole("button", { name: "测试任务的操作菜单" }))
    const item = await screen.findByText("运行中不可删除")
    expect(item.closest("[data-disabled]")).toBeInTheDocument()
  })

  it("cancels a running task after confirmation", async () => {
    const onChanged = vi.fn()
    const runningTask = { ...task, status: "running" } as VideoTask
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      expect(String(input)).toContain(`/api/tasks/${task.id}/cancel`)
      expect(init?.method).toBe("POST")
      return new Response(JSON.stringify({
        id: task.id,
        status: "running",
        cancel_requested_at: "2026-10-15T21:40:00+08:00",
        terminated_pids: [661],
      }), { status: 202, headers: { "Content-Type": "application/json" } })
    })
    vi.stubGlobal("fetch", fetchMock)

    render(<TaskActionsMenu task={runningTask} onDeleted={vi.fn()} onChanged={onChanged} />)

    fireEvent.click(screen.getByRole("button", { name: "测试任务的操作菜单" }))
    fireEvent.click(await screen.findByText("终止任务"))

    // 确认框要说明「产物会保留」：用户怕的是终止之后视频要重新下载。
    const dialog = await screen.findByRole("alertdialog")
    expect(within(dialog).getByText(/产物全部保留/)).toBeInTheDocument()
    fireEvent.click(within(dialog).getByRole("button", { name: "终止任务" }))

    await waitFor(() => expect(onChanged).toHaveBeenCalledOnce())
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it("disables cancelling for finished tasks and while cancelling", async () => {
    const completedTask = { ...task, status: "completed" } as VideoTask
    const { unmount } = render(<TaskActionsMenu task={completedTask} onDeleted={vi.fn()} />)

    fireEvent.click(screen.getByRole("button", { name: "测试任务的操作菜单" }))
    const idle = await screen.findByText("终止任务")
    expect(idle.closest("[data-disabled]")).toBeInTheDocument()
    unmount()

    // 已经发出终止请求、流水线还在收尾时，重复点击没有意义。
    const cancellingTask = {
      ...task,
      status: "running",
      cancel_requested_at: "2026-10-15T21:40:00+08:00",
    } as VideoTask
    render(<TaskActionsMenu task={cancellingTask} onDeleted={vi.fn()} />)

    fireEvent.click(screen.getByRole("button", { name: "测试任务的操作菜单" }))
    const busy = await screen.findByText("正在终止…")
    expect(busy.closest("[data-disabled]")).toBeInTheDocument()
  })
})
