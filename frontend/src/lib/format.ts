import type { VideoResult, VideoTask } from "@/types"

export function formatDate(value: string | null | undefined): string {
  if (!value) {
    return "—"
  }
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value))
}

export function formatSeconds(value: number): string {
  const total = Math.max(0, Math.round(value))
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const seconds = total % 60
  if (hours > 0) {
    return [hours, minutes, seconds].map((item) => String(item).padStart(2, "0")).join(":")
  }
  return [minutes, seconds].map((item) => String(item).padStart(2, "0")).join(":")
}

export function formatBytes(value: number): string {
  const bytes = Math.max(0, value)
  if (bytes < 1024) {
    return `${bytes} B`
  }
  const units = ["KB", "MB", "GB", "TB"]
  let amount = bytes / 1024
  let unitIndex = 0
  while (amount >= 1024 && unitIndex < units.length - 1) {
    amount /= 1024
    unitIndex += 1
  }
  const digits = amount >= 10 ? 0 : 1
  return `${amount.toFixed(digits)} ${units[unitIndex]}`
}

export function taskTitle(task: VideoTask): string {
  return task.article_title || task.metadata.title || task.url
}

export function resultTitle(result: VideoResult): string {
  return result.article_title || result.outline.title || result.metadata.title || "未命名文章"
}
