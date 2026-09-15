import { Badge } from "@/components/ui/badge"
import type { StepStatus, TaskStatus } from "@/types"

const labels: Record<TaskStatus | StepStatus, string> = {
  queued: "等待中",
  running: "运行中",
  completed: "已完成",
  failed: "失败",
  cancelled: "已取消",
  interrupted: "已中断",
  pending: "未开始",
  skipped: "已跳过",
}

export function StatusBadge({ status }: { status: TaskStatus | StepStatus }) {
  let variant: "default" | "secondary" | "destructive" | "outline" | "ghost" = "secondary"
  if (status === "completed") {
    variant = "default"
  } else if (status === "running") {
    variant = "secondary"
  } else if (status === "failed") {
    variant = "destructive"
  } else if (status === "interrupted" || status === "cancelled") {
    variant = "outline"
  } else if (status === "skipped") {
    variant = "ghost"
  }
  return <Badge variant={variant}>{labels[status]}</Badge>
}
