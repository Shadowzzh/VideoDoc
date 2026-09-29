import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { App } from "@/app"
import { TooltipProvider } from "@/components/ui/tooltip"

const result = {
  metadata: { title: "测试视频", uploader: "作者", extractor: "test" },
  article_title: "AI 中文文章标题",
  video: "video/source.mp4",
  segments: [{ id: "seg-00001", start_sec: 0, end_sec: 2, text: "开场内容" }],
  outline: {
    title: "测试大纲",
    summary: "大纲摘要",
    sections: [
      {
        id: "section-01",
        title: "开场章节",
        summary: "章节摘要",
        start_segment_id: "seg-00001",
        end_segment_id: "seg-00001",
        start_sec: 0,
        end_sec: 2,
        start_time: "00:00",
        end_time: "00:02",
      },
    ],
  },
  images: [],
  article_markdown: "article.md",
  article_html: '<h1>生成文章</h1><h2>开场章节</h2><p>文章正文</p><a href="#t=12">跳到视频</a>',
}

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

const scrollResult = {
  ...result,
  article_title: "滚动联动文章",
  outline: {
    ...result.outline,
    sections: [
      result.outline.sections[0],
      {
        ...result.outline.sections[0],
        id: "section-02",
        title: "第二章",
        start_sec: 10,
        end_sec: 20,
        start_time: "00:10",
        end_time: "00:20",
      },
    ],
  },
  article_html: "<h1>生成文章</h1><h2>开场章节</h2><p>一段</p><h2>第二章</h2><p>二段</p>",
}

describe("VideoDoc app", () => {
  it("renders the text-first result workspace", async () => {
    window.history.pushState({}, "", "/app/tasks/task-1/result")
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      const payload = url === "/api/tasks" ? [] : result
      return new Response(JSON.stringify(payload), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
    }))

    const scrollIntoView = vi.spyOn(Element.prototype, "scrollIntoView")
    render(<TooltipProvider><App /></TooltipProvider>)

    expect(await screen.findByText("生成文章")).toBeInTheDocument()
    expect(screen.getAllByText("AI 中文文章标题")).toHaveLength(2)
    expect(document.title).toBe("AI 中文文章标题 · VideoDoc")
    expect(screen.getByRole("button", { name: /处理流程/ })).toHaveAttribute("href", "/app/tasks/task-1")
    expect(screen.getByText("文章大纲")).toBeInTheDocument()
    expect(screen.getAllByText("开场章节")).toHaveLength(3)
    expect(screen.getByText("视频浮窗")).toBeInTheDocument()
    expect(screen.getByRole("tab", { name: /文章/ })).toHaveAttribute("data-active")
    expect(screen.getByRole("button", { name: "放大视频" })).toBeInTheDocument()

    fireEvent.click(screen.getByRole("tab", { name: /转写/ }))
    expect(screen.getByRole("tab", { name: /转写/ })).toHaveAttribute("data-active")
    fireEvent.click(screen.getByRole("button", { name: /01.*00:00.*开场章节/ }))
    await waitFor(() => expect(screen.getByRole("tab", { name: /文章/ })).toHaveAttribute("data-active"))
    expect(scrollIntoView).toHaveBeenCalledWith({ behavior: "smooth", block: "start" })
    expect(window.location.hash).toBe("#article-section-01")

    fireEvent.click(screen.getByText("跳到视频"))
    const video = document.querySelector("video")
    expect(video).not.toBeNull()
    await new Promise((resolve) => window.setTimeout(resolve, 0))
    fireEvent.loadedMetadata(video as HTMLVideoElement)
    await waitFor(() => expect(video?.currentTime).toBe(12))

    const play = vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue(undefined)
    const pause = vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => undefined)
    fireEvent.keyDown(window, { code: "KeyK", key: "k" })
    expect(play).toHaveBeenCalled()

    Object.defineProperty(video, "paused", { configurable: true, value: false })
    fireEvent.keyDown(window, { code: "KeyK", key: "k" })
    expect(pause).toHaveBeenCalled()

    const input = document.createElement("input")
    document.body.append(input)
    input.focus()
    play.mockClear()
    pause.mockClear()
    fireEvent.keyDown(input, { code: "KeyK", key: "k" })
    expect(play).not.toHaveBeenCalled()
    expect(pause).not.toHaveBeenCalled()
    input.remove()

    fireEvent.keyDown(window, { code: "KeyV", key: "v" })
    expect(screen.getByRole("button", { name: "缩小视频" })).toBeInTheDocument()
    await waitFor(() => expect(document.activeElement).toBe(video))
    fireEvent.keyDown(window, { code: "Escape", key: "Escape" })
    expect(screen.getByRole("button", { name: "放大视频" })).toBeInTheDocument()

    fireEvent.click(screen.getByRole("button", { name: "隐藏视频" }))
    expect(screen.getByText("显示视频")).toBeInTheDocument()
  })

  it("highlights the outline entry matching the article scroll position without touching the video", async () => {
    window.history.pushState({}, "", "/app/tasks/task-2/result")
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      const payload = url === "/api/tasks" ? [] : scrollResult
      return new Response(JSON.stringify(payload), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
    }))

    render(<TooltipProvider><App /></TooltipProvider>)
    await screen.findByText("生成文章")

    const article = document.querySelector("article")
    const viewport = article?.closest('[data-slot="scroll-area-viewport"]') as HTMLElement | null
    expect(article).not.toBeNull()
    expect(viewport).not.toBeNull()

    const headings = Array.from(article!.querySelectorAll("h2"))
    const rect = (top: number) => ({
      top,
      bottom: top + 40,
      left: 0,
      right: 0,
      width: 0,
      height: 40,
      x: 0,
      y: top,
      toJSON: () => ({}),
    }) as DOMRect
    let secondTop = 300
    vi.spyOn(Element.prototype, "getBoundingClientRect").mockImplementation(function (this: Element) {
      if (this === viewport) {
        return rect(0)
      }
      if (this === headings[0]) {
        return rect(-200)
      }
      if (this === headings[1]) {
        return rect(secondTop)
      }
      return rect(0)
    })
    Object.defineProperty(viewport!, "clientHeight", { configurable: true, value: 800 })
    Object.defineProperty(viewport!, "scrollHeight", { configurable: true, value: 4000 })
    Object.defineProperty(viewport!, "scrollTop", { configurable: true, value: 200 })

    const firstEntry = screen.getByRole("button", { name: /01.*开场章节/ })
    const secondEntry = screen.getByRole("button", { name: /02.*00:10.*第二章/ })

    fireEvent.scroll(viewport!)
    await waitFor(() => expect(firstEntry).toHaveClass("bg-sidebar-accent"))
    expect(secondEntry).not.toHaveClass("bg-sidebar-accent")

    secondTop = 60
    fireEvent.scroll(viewport!)
    await waitFor(() => expect(secondEntry).toHaveClass("bg-sidebar-accent"))
    expect(firstEntry).not.toHaveClass("bg-sidebar-accent")

    // 视频浮窗仍由播放进度驱动，不受文章滚动影响。
    const assistant = document.querySelector('[aria-label="视频浮窗"]')
    expect(assistant).not.toBeNull()
    expect(within(assistant as HTMLElement).getByText("开场章节")).toBeInTheDocument()
  })

  it("resumes a failed task from its current stage", async () => {
    window.history.pushState({}, "", "/app/tasks/task-1")
    let resumed = false
    const task = {
      id: "task-1",
      url: "https://example.com/video",
      status: "failed",
      created_at: "2026-09-11T10:00:00+08:00",
      updated_at: "2026-09-11T10:01:00+08:00",
      started_at: "2026-09-11T10:00:00+08:00",
      finished_at: "2026-09-11T10:01:00+08:00",
      error: "模型 JSON 无法解析",
      metadata: { title: "失败任务" },
      artifacts: {},
      resume_count: 0,
      can_resume: true,
      resume_from: { key: "article", label: "DeepSeek 生成图文正文" },
      progress: { completed: 8, total: 10, percent: 80 },
      steps: [
        {
          key: "article",
          label: "DeepSeek 生成图文正文",
          status: "failed",
          started_at: "2026-09-11T10:00:00+08:00",
          finished_at: "2026-09-11T10:01:00+08:00",
          command: "POST DeepSeek",
          outputs: ["article-progress.json"],
          error: "模型 JSON 无法解析",
          attempt_count: 3,
          attempts: [],
          log_tail: "失败",
        },
      ],
    }
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url === "/api/tasks") {
        return new Response("[]", { status: 200 })
      }
      if (url.endsWith("/resume") && init?.method === "POST") {
        resumed = true
        return new Response(JSON.stringify({ id: "task-1", resume_from: "article" }), {
          status: 202,
          headers: { "Content-Type": "application/json" },
        })
      }
      const current = resumed
        ? { ...task, status: "queued", error: null, can_resume: false, resume_from: null }
        : task
      return new Response(JSON.stringify(current), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
    })
    vi.stubGlobal("fetch", fetchMock)

    render(<TooltipProvider><App /></TooltipProvider>)

    const resumeButton = await screen.findByRole("button", { name: /重试当前阶段/ })
    expect(screen.getByText(/将从「DeepSeek 生成图文正文」继续/)).toBeInTheDocument()
    fireEvent.click(resumeButton)

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/tasks/task-1/resume",
        expect.objectContaining({ method: "POST" }),
      )
    })
    await waitFor(() => expect(screen.getByText("等待中")).toBeInTheDocument())
  })
})
