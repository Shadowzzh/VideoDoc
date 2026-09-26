import { ArrowLeftIcon, SettingsIcon } from "lucide-react"
import { useEffect, useMemo, useState } from "react"

import { AppShell } from "@/components/app-shell"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Separator } from "@/components/ui/separator"
import { getSettings, testSettings, updateSettings } from "@/lib/api"
import type {
  SettingsCapabilityResult,
  SettingsCategory,
  SettingsField,
  SettingsResponse,
  SettingsTestResult,
  SettingsUpdate,
  SettingsValue,
} from "@/types"

const selectClass =
  "h-7 w-full rounded-md border border-input bg-input/20 px-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/30 disabled:opacity-50 dark:bg-input/30"
const textareaClass =
  "min-h-20 w-full rounded-md border border-input bg-input/20 p-2 font-mono text-xs leading-5 outline-none focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/30 dark:bg-input/30"
const labelClass = "text-xs font-medium text-muted-foreground"

/** 表单草稿：capabilities.<能力 key>.<点分字段 key> = 值。 */
type Draft = Record<string, Record<string, SettingsValue>>

function fieldPlaceholder(field: SettingsField, saved: Record<string, SettingsValue>): string {
  if (field.secret) {
    if (saved[`${field.key}_configured`]) {
      const hint = saved[`${field.key}_hint`]
      return `已配置${hint ? `（${hint}）` : ""}，留空保持不变`
    }
    return field.placeholder || "未配置"
  }
  return field.placeholder
}

function initialDraft(settings: SettingsResponse): Draft {
  const draft: Draft = {}
  for (const category of settings.categories) {
    const current = settings.capabilities[category.key] ?? {}
    const values: Record<string, SettingsValue> = {}
    for (const group of category.groups) {
      for (const field of group.fields) {
        if (field.secret) {
          // 密钥永不回显：留空表示「保持已保存的值」。
          values[field.key] = ""
          continue
        }
        const value = current[field.key]
        values[field.key] = value ?? (field.type === "boolean" ? false : field.type === "number" ? 0 : "")
      }
    }
    draft[category.key] = values
  }
  return draft
}

function visible(field: SettingsField, values: Record<string, SettingsValue>): boolean {
  if (!field.show_when) {
    return true
  }
  return String(values[field.show_when.key] ?? "") === field.show_when.value
}

function FieldRow({
  field,
  values,
  placeholder,
  onChange,
}: {
  field: SettingsField
  values: Record<string, SettingsValue>
  placeholder: string
  onChange: (value: SettingsValue) => void
}) {
  const id = `setting-${field.key.replace(/[._]/g, "-")}`
  const help = field.help ? <p className="text-[11px] text-muted-foreground">{field.help}</p> : null
  const value = values[field.key]

  if (field.type === "boolean") {
    return (
      <div className="space-y-1">
        <label className="flex items-center gap-2 text-sm" htmlFor={id}>
          <input
            id={id}
            type="checkbox"
            checked={Boolean(value)}
            onChange={(event) => onChange(event.target.checked)}
          />
          {field.label}
        </label>
        {help}
      </div>
    )
  }

  return (
    <div className="space-y-1">
      <label className={labelClass} htmlFor={id}>
        {field.label}
      </label>
      {field.type === "select" ? (
        <select
          id={id}
          className={selectClass}
          value={String(value ?? "")}
          onChange={(event) => onChange(event.target.value)}
        >
          {field.options.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      ) : field.type === "textarea" ? (
        <textarea
          id={id}
          className={textareaClass}
          value={String(value ?? "")}
          placeholder={placeholder}
          onChange={(event) => onChange(event.target.value)}
        />
      ) : (
        <Input
          id={id}
          type={field.type === "password" ? "password" : field.type === "number" ? "number" : "text"}
          min={field.minimum ?? undefined}
          max={field.maximum ?? undefined}
          value={String(value ?? "")}
          placeholder={placeholder}
          onChange={(event) => onChange(field.type === "number" ? Number(event.target.value) : event.target.value)}
        />
      )}
      {help}
    </div>
  )
}

function ChannelLine({ name, result }: { name: string; result: SettingsCapabilityResult["local"] }) {
  if (!result) {
    return null
  }
  return (
    <div>
      {name}：{result.ok ? "✅" : "❌"} {result.detail}
      {result.endpoint ? (
        <span className="ml-2 font-mono text-xs text-muted-foreground">{result.endpoint}</span>
      ) : null}
    </div>
  )
}

/** 设置页的左侧导航（占用 Shell 的 sidebar 槽位）：这里展示「设置分类」，不再是任务列表。 */
function SettingsNav({
  categories,
  selected,
  onSelect,
}: {
  categories: SettingsCategory[]
  selected: string
  onSelect: (key: string) => void
}) {
  return (
    <aside className="flex h-full min-h-0 w-full flex-col bg-sidebar text-sidebar-foreground">
      <div className="flex h-14 shrink-0 items-center gap-2 px-4">
        <SettingsIcon className="size-4 shrink-0" />
        <a href="/app/" className="truncate font-semibold tracking-tight">
          VideoDoc
        </a>
        <span className="shrink-0 text-[11px] text-muted-foreground">设置</span>
      </div>
      <Separator />
      <p className="px-4 pb-1 pt-3 text-xs font-medium text-muted-foreground">设置分类</p>
      <div className="space-y-1 px-2">
        {categories.map((item) => (
          <button
            key={item.key}
            type="button"
            onClick={() => onSelect(item.key)}
            data-active={item.key === selected ? "true" : undefined}
            className="flex w-full items-center justify-between rounded-md px-2 py-1.5 text-left text-sm hover:bg-muted data-[active]:bg-muted"
          >
            <span className="truncate">{item.label}</span>
            {item.available ? null : (
              <span className="ml-2 shrink-0 text-[10px] text-muted-foreground">不可用</span>
            )}
          </button>
        ))}
      </div>
      <div className="mt-auto p-3">
        <Button
          nativeButton={false}
          variant="ghost"
          render={<a href="/app/" />}
          className="w-full justify-start"
        >
          <ArrowLeftIcon />返回任务台
        </Button>
      </div>
    </aside>
  )
}

export function SettingsPage() {
  const [settings, setSettings] = useState<SettingsResponse | null>(null)
  const [draft, setDraft] = useState<Draft | null>(null)
  const [selected, setSelected] = useState<string>("")
  const [loadError, setLoadError] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [testResult, setTestResult] = useState<SettingsTestResult | null>(null)
  const [busy, setBusy] = useState<"save" | "test" | null>(null)

  useEffect(() => {
    let active = true
    getSettings()
      .then((value) => {
        if (!active) return
        setSettings(value)
        setDraft(initialDraft(value))
        setSelected(value.categories[0]?.key ?? "")
      })
      .catch((reason: unknown) => {
        if (active) setLoadError(reason instanceof Error ? reason.message : "读取设置失败")
      })
    return () => {
      active = false
    }
  }, [])

  const category: SettingsCategory | undefined = useMemo(
    () => settings?.categories.find((item) => item.key === selected),
    [settings, selected]
  )
  const values = draft?.[selected] ?? {}
  // 密钥的「已配置 / 末 4 位」来自服务端响应（草稿里不回显密钥）。
  const savedValues = settings?.capabilities[selected] ?? {}

  const patch = (fieldKey: string, value: SettingsValue) => {
    setDraft((current) =>
      current ? { ...current, [selected]: { ...(current[selected] ?? {}), [fieldKey]: value } } : current
    )
    setNotice(null)
    setTestResult(null)
  }

  const payload = (): SettingsUpdate => {
    if (!category) return {}
    const onlyNonEmptySecrets: Record<string, SettingsValue> = {}
    for (const group of category.groups) {
      for (const field of group.fields) {
        const value = values[field.key]
        if (field.secret && String(value ?? "").trim() === "") continue
        onlyNonEmptySecrets[field.key] = value
      }
    }
    return { capabilities: { [category.key]: onlyNonEmptySecrets } }
  }

  const handleSave = async () => {
    if (!category) return
    setBusy("save")
    setError(null)
    setNotice(null)
    try {
      const updated = await updateSettings(payload())
      setSettings(updated)
      setDraft(initialDraft(updated))
      setSelected(category.key)
      setNotice("已保存。新任务立即生效（无需重启服务）。")
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "保存失败")
    } finally {
      setBusy(null)
    }
  }

  const handleTest = async () => {
    setBusy("test")
    setError(null)
    setNotice(null)
    setTestResult(null)
    try {
      setTestResult(await testSettings(payload()))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "测试失败")
    } finally {
      setBusy(null)
    }
  }

  if (loadError) {
    return (
      <AppShell>
        <div className="mx-auto max-w-2xl p-8 text-sm text-destructive">{loadError}</div>
      </AppShell>
    )
  }

  if (!settings || !draft) {
    return (
      <AppShell>
        <div className="mx-auto max-w-2xl p-8 text-sm text-muted-foreground">正在读取设置…</div>
      </AppShell>
    )
  }

  return (
    <AppShell
      sidebarLabel="设置分类"
      renderSidebar={(onNavigate) => (
        <SettingsNav
          categories={settings.categories}
          selected={selected}
          onSelect={(key) => {
            setSelected(key)
            setNotice(null)
            setTestResult(null)
            onNavigate?.()
          }}
        />
      )}
    >
      <div className="flex h-full min-h-0">
        <ScrollArea className="min-h-0 flex-1">
          <div className="mx-auto w-full max-w-3xl space-y-5 px-5 py-8 md:px-8">
            <div className="space-y-1">
              <h1 className="text-2xl font-semibold tracking-tight">{category?.label ?? "设置"}</h1>
              <p className="text-sm text-muted-foreground">{category?.description}</p>
              {category && !category.available ? (
                <p className="text-sm text-amber-600 dark:text-amber-500">
                  {category.unavailable_reason}
                </p>
              ) : null}
            </div>

            {notice ? (
              <div className="rounded-lg border border-emerald-500/40 bg-emerald-500/10 p-3 text-sm">{notice}</div>
            ) : null}
            {error ? (
              <div className="rounded-lg border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
                {error}
              </div>
            ) : null}

            {category?.groups.map((group) => (
              <Card key={group.title}>
                <CardHeader>
                  <CardTitle>{group.title}</CardTitle>
                  {group.description ? <CardDescription>{group.description}</CardDescription> : null}
                </CardHeader>
                <CardContent className="grid gap-3 md:grid-cols-2">
                  {group.fields
                    .filter((field) => visible(field, values))
                    .map((field) => (
                      <div
                        key={field.key}
                        className={field.type === "textarea" ? "md:col-span-2" : undefined}
                      >
                        <FieldRow
                          field={field}
                          values={values}
                          placeholder={fieldPlaceholder(field, savedValues)}
                          onChange={(value) => patch(field.key, value)}
                        />
                      </div>
                    ))}
                </CardContent>
              </Card>
            ))}

            <Separator />

            <div className="flex flex-wrap items-center gap-3">
              <Button onClick={() => void handleSave()} disabled={busy !== null || !category}>
                {busy === "save" ? "保存中…" : "保存设置"}
              </Button>
              <Button variant="outline" onClick={() => void handleTest()} disabled={busy !== null}>
                {busy === "test" ? "测试中…" : "测试连接"}
              </Button>
              <span className="text-xs text-muted-foreground">
                测试只打各协议的 /models，不消耗图像识别额度。
              </span>
            </div>

            {testResult ? (
              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    测试结果
                    <Badge variant={testResult.ok ? "secondary" : "destructive"}>
                      {testResult.ok ? "可用" : "不可用"}
                    </Badge>
                  </CardTitle>
                  {testResult.engine ? <CardDescription>生效通道：{testResult.engine}</CardDescription> : null}
                </CardHeader>
                <CardContent className="space-y-2 text-sm">
                  <ChannelLine name="本地" result={testResult.local} />
                  <ChannelLine name="云端" result={testResult.external} />
                  {testResult.detail ? (
                    <div className="text-muted-foreground">{testResult.detail}</div>
                  ) : null}
                </CardContent>
              </Card>
            ) : null}

            <p className="pb-8 text-xs text-muted-foreground">
              设置文件：<span className="font-mono">{settings.settings_path}</span>　·　环境变量提供默认值，
              页面保存的值优先；改完对新任务立即生效。
            </p>
          </div>
        </ScrollArea>
      </div>
    </AppShell>
  )
}
