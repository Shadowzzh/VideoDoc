import { AlertCircleIcon } from "lucide-react"
import type { ReactNode } from "react"

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"

/**
 * 提示卡片。
 *
 * ``tone="neutral"`` 给「已取消」这类**不是错误**的状态用：用户主动终止却被画成
 * 红色失败横幅，会让人以为任务出问题了。
 */
export function ErrorState({
  title = "加载失败",
  message,
  tone = "destructive",
  icon,
}: {
  title?: string
  message: string
  tone?: "destructive" | "neutral"
  icon?: ReactNode
}) {
  const destructive = tone === "destructive"
  return (
    <Card className={destructive ? "border-destructive/30 bg-destructive/5" : "border-border bg-muted/40"}>
      <CardHeader className="pb-0">
        <CardTitle className={`flex items-center gap-2 text-base ${destructive ? "text-destructive" : ""}`}>{icon ?? <AlertCircleIcon className="size-4" />}{title}</CardTitle>
      </CardHeader>
      <CardContent className="text-sm text-muted-foreground">{message}</CardContent>
    </Card>
  )
}
