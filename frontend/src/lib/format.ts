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

/** 阶段耗时的人读格式：毫秒级不四舍五入成 00:00，分钟级以上不用数秒数。 */
export function formatDurationMilliseconds(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "—"
  }
  const ms = Math.max(0, value)
  if (ms < 1000) {
    return `${Math.round(ms)} ms`
  }
  const seconds = ms / 1000
  if (seconds < 60) {
    return `${seconds.toFixed(1)} s`
  }
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) {
    return `${minutes}m ${String(Math.round(seconds % 60)).padStart(2, "0")}s`
  }
  const hours = Math.floor(minutes / 60)
  return `${hours}h ${String(minutes % 60).padStart(2, "0")}m`
}

/** 占比格式化：小于 1% 不写成 0%，保留一位小数以免被大阶段吃掉。 */
export function formatPercent(value: number): string {
  if (!Number.isFinite(value) || value <= 0) {
    return "0%"
  }
  if (value < 1) {
    return "<1%"
  }
  if (value >= 10) {
    return `${Math.round(value)}%`
  }
  return `${value.toFixed(1)}%`
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

/**
 * 弹窗这类固定宽度容器里用的短标题。
 *
 * taskTitle 在没有文章标题时会退回原始 URL，抖音/YouTube 的分享链接动辄两三百
 * 字符且没有空格，塞进 AlertDialog 会直接撑出白框边界；这里按字符数截断，保留
 * 前段的域名与路径（用户据此能认出是哪条任务），砍掉后半段追踪参数。
 */
export function taskTitleShort(task: VideoTask, max = 60): string {
  const title = taskTitle(task)
  if (title.length <= max) {
    return title
  }
  return `${title.slice(0, max - 1)}…`
}

export function resultTitle(result: VideoResult): string {
  return result.article_title || result.outline.title || result.metadata.title || "未命名文章"
}
