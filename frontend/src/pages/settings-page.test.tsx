import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { App } from "@/app"
import { TooltipProvider } from "@/components/ui/tooltip"

const settingsPayload = {
  capabilities: {
    image_vision: {
      engine: "auto",
      "local.enabled": true,
      "local.script": "/repo/videodoc/integrations/vision_ocr.swift",
      "local.language": "zh-Hans,en-US",
      "local.level": "accurate",
      "external.protocol": "openai-chat",
      "external.base_url": "",
      "external.model": "",
      "external.api_key_file": "",
      "external.extra_headers": {},
      "external.prompt": "默认提示词",
      "external.max_frames": 12,
      "external.daily_budget": 200,
      "external.api_key_configured": false,
      "external.api_key_hint": "",
    },
  },
  categories: [
    {
      key: "image_vision",
      label: "图像识别",
      description: "把配图变成任务可用的图像证据。",
      available: true,
      unavailable_reason: "",
      groups: [
        {
          title: "识别通道",
          description: "决定图像证据从哪来。",
          fields: [
            {
              key: "engine",
              label: "通道",
              type: "select",
              help: "",
              placeholder: "",
              options: [
                { value: "auto", label: "自动" },
                { value: "external", label: "仅云端（外部视觉模型）" },
              ],
              minimum: null,
              maximum: null,
              secret: false,
              show_when: null,
            },
          ],
        },
        {
          title: "云端（视觉模型理解）",
          description: "配好它就不依赖 macOS。",
          fields: [
            {
              key: "external.base_url",
              label: "BaseURL",
              type: "text",
              help: "含版本路径。",
              placeholder: "https://api.openai.com/v1",
              options: [],
              minimum: null,
              maximum: null,
              secret: false,
              show_when: null,
            },
            {
              key: "external.model",
              label: "模型",
              type: "text",
              help: "",
              placeholder: "gpt-4o-mini",
              options: [],
              minimum: null,
              maximum: null,
              secret: false,
              show_when: null,
            },
            {
              key: "external.api_key",
              label: "API Key",
              type: "password",
              help: "明文保存，接口不回显。",
              placeholder: "粘贴明文 Key",
              options: [],
              minimum: null,
              maximum: null,
              secret: true,
              show_when: null,
            },
          ],
        },
        {
          title: "预算与重试",
          description: "",
          fields: [
            {
              key: "external.max_frames",
              label: "每任务云端上限（张）",
              type: "number",
              help: "",
              placeholder: "",
              options: [],
              minimum: 0,
              maximum: 24,
              secret: false,
              show_when: null,
            },
          ],
        },
      ],
    },
  ],
  settings_path: "/tmp/videodoc-settings.json",
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  })
}

interface Recorded {
  url: string
  method: string
  body: Record<string, unknown> | null
}

function stubFetch(overrides: { put?: () => Response; test?: () => Response } = {}) {
  const calls: Recorded[] = []
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const method = init?.method ?? "GET"
      const body = init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : null
      calls.push({ url, method, body })
      if (url === "/api/tasks") return jsonResponse([])
      if (url === "/api/settings/test") {
        return overrides.test
          ? overrides.test()
          : jsonResponse({
              ok: true,
              engine: "both",
              local: { ok: true, detail: "可用" },
              external: { ok: true, detail: "可达（模型数 3）", endpoint: "http://h/v1/models" },
            })
      }
      if (url === "/api/settings" && method === "PUT") {
        return overrides.put ? overrides.put() : jsonResponse(settingsPayload)
      }
      if (url === "/api/settings") return jsonResponse(settingsPayload)
      return jsonResponse({}, 404)
    })
  )
  return calls
}

function renderSettings() {
  window.history.pushState({}, "", "/app/settings")
  render(
    <TooltipProvider>
      <App />
    </TooltipProvider>
  )
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe("设置页（左分类 / 右设置项）", () => {
  it("按后端 schema 渲染左分类与右侧分组设置项", async () => {
    stubFetch()

    renderSettings()

    expect(await screen.findByRole("heading", { name: "图像识别" })).toBeInTheDocument()
    // 左侧 sidebar 换成「设置分类」，不再显示任务/项目列表
    expect(screen.queryByText("最近任务")).toBeNull()
    expect(screen.getByRole("button", { name: "返回任务台" })).toBeInTheDocument()
    // 左侧分类
    expect(screen.getByText("设置分类")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "图像识别" })).toHaveAttribute("data-active")
    // 右侧分组标题来自 schema，不是前端硬编码
    expect(screen.getByText("识别通道")).toBeInTheDocument()
    expect(screen.getByText("云端（视觉模型理解）")).toBeInTheDocument()
    expect(screen.getByText("预算与重试")).toBeInTheDocument()
    // 字段与当前值
    expect(screen.getByLabelText("BaseURL")).toHaveValue("")
    expect(screen.getByLabelText("通道")).toHaveValue("auto")
    expect(screen.getByLabelText("每任务云端上限（张）")).toHaveValue(12)
    // 密钥不回显：输入框为空，占位符用 schema 里的提示
    expect(screen.getByLabelText("API Key")).toHaveValue("")
    expect(screen.getByLabelText("API Key")).toHaveAttribute("placeholder", "粘贴明文 Key")
    expect(screen.getByText("/tmp/videodoc-settings.json")).toBeInTheDocument()
  })

  it("保存时按 schema 的字段 key 组装 capabilities.<能力> 负载，空密钥不提交", async () => {
    const calls = stubFetch()
    renderSettings()
    await screen.findByRole("heading", { name: "图像识别" })

    fireEvent.change(screen.getByLabelText("通道"), { target: { value: "external" } })
    fireEvent.change(screen.getByLabelText("BaseURL"), { target: { value: "http://192.168.8.211:3006/v1" } })
    fireEvent.change(screen.getByLabelText("模型"), { target: { value: "gemini-3.5-flash-lite" } })
    fireEvent.change(screen.getByLabelText("每任务云端上限（张）"), { target: { value: "6" } })
    fireEvent.click(screen.getByRole("button", { name: "保存设置" }))

    await waitFor(() => expect(screen.getByText(/已保存/)).toBeInTheDocument())
    const put = calls.find((call) => call.method === "PUT")
    const section = (put?.body as { capabilities: Record<string, Record<string, unknown>> }).capabilities
      .image_vision
    expect(section.engine).toBe("external")
    expect(section["external.base_url"]).toBe("http://192.168.8.211:3006/v1")
    expect(section["external.model"]).toBe("gemini-3.5-flash-lite")
    expect(section["external.max_frames"]).toBe(6)
    expect("external.api_key" in section).toBe(false)
  })

  it("填了明文密钥就提交，保存后输入框清空并显示已配置提示", async () => {
    const calls = stubFetch({
      put: () =>
        jsonResponse({
          ...settingsPayload,
          capabilities: {
            image_vision: {
              ...settingsPayload.capabilities.image_vision,
              "external.base_url": "http://h/v1",
              "external.api_key_configured": true,
              "external.api_key_hint": "****abcd",
            },
          },
        }),
    })
    renderSettings()
    await screen.findByRole("heading", { name: "图像识别" })

    fireEvent.change(screen.getByLabelText("BaseURL"), { target: { value: "http://h/v1" } })
    fireEvent.change(screen.getByLabelText("API Key"), { target: { value: "plain-secret-abcd" } })
    fireEvent.click(screen.getByRole("button", { name: "保存设置" }))

    await waitFor(() => expect(screen.getByText(/已保存/)).toBeInTheDocument())
    const put = calls.find((call) => call.method === "PUT")
    const section = (put?.body as { capabilities: Record<string, Record<string, unknown>> }).capabilities
      .image_vision
    expect(section["external.api_key"]).toBe("plain-secret-abcd")
    expect(screen.getByLabelText("API Key")).toHaveValue("")
    expect(screen.getByLabelText("API Key")).toHaveAttribute("placeholder", "已配置（****abcd），留空保持不变")
  })

  it("测试连接走后端探测并展示两条通道", async () => {
    const calls = stubFetch()
    renderSettings()
    await screen.findByRole("heading", { name: "图像识别" })

    fireEvent.change(screen.getByLabelText("BaseURL"), { target: { value: "http://h/v1" } })
    fireEvent.click(screen.getByRole("button", { name: "测试连接" }))

    expect(await screen.findByText("可用")).toBeInTheDocument()
    expect(screen.getByText(/http:\/\/h\/v1\/models/)).toBeInTheDocument()
    expect(calls.some((call) => call.url === "/api/settings/test" && call.method === "POST")).toBe(true)
  })

  it("后端校验失败时显示原始错误原因", async () => {
    stubFetch({ put: () => jsonResponse({ error: "BaseURL 必须以 http:// 或 https:// 开头。" }, 400) })
    renderSettings()
    await screen.findByRole("heading", { name: "图像识别" })

    fireEvent.click(screen.getByRole("button", { name: "保存设置" }))

    expect(await screen.findByText(/BaseURL 必须以 http/)).toBeInTheDocument()
  })

  it("能力不可用时在右侧显示原因", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input)
        if (url === "/api/tasks") return jsonResponse([])
        if (url === "/api/settings") {
          return jsonResponse({
            ...settingsPayload,
            categories: [
              {
                ...settingsPayload.categories[0],
                available: false,
                unavailable_reason: "无可用通道（本地：当前环境缺少 swift；云端：未配置图像识别 BaseURL）",
              },
            ],
          })
        }
        return jsonResponse({}, 404)
      })
    )

    renderSettings()

    expect(await screen.findByText(/无可用通道/)).toBeInTheDocument()
    expect(screen.getByText("不可用")).toBeInTheDocument()
  })
})
