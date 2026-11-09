import { CaptionsIcon, LanguagesIcon } from "lucide-react"
import { useState } from "react"

import { toast } from "@/components/toast"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { addSubtitle } from "@/lib/api"
import type { VideoTask } from "@/types"

interface SubtitleMenuButtonProps {
  task: VideoTask
  /** 提交后回调；任务页用它触发轮询，列表页用它刷新列表。 */
  onChanged?: () => void
  disabled?: boolean
}

/**
 * 显式的「生成字幕」按钮：任务详情页和结果页都放一个。
 * 只藏在 ⋯ 菜单里时用户找不到，而且点完没有任何反馈。
 */
export function SubtitleMenuButton({ task, onChanged, disabled }: SubtitleMenuButtonProps) {
  const [pending, setPending] = useState(false)

  if (!task.artifacts?.transcript_segments) {
    return null
  }

  const run = async (mode: "zh" | "bilingual") => {
    setPending(true)
    try {
      await addSubtitle(task.id, mode)
      toast(mode === "zh" ? "已提交：正在生成中文字幕" : "已提交：正在生成中英字幕")
      onChanged?.()
    } catch (reason) {
      toast(reason instanceof Error ? reason.message : "补字幕失败", "error")
    } finally {
      setPending(false)
    }
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger render={<Button variant="outline" disabled={disabled || pending} />}>
        <CaptionsIcon />
        {pending ? "提交中…" : "生成字幕"}
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuItem onClick={() => void run("zh")}>
          <CaptionsIcon />
          中文字幕
        </DropdownMenuItem>
        <DropdownMenuItem onClick={() => void run("bilingual")}>
          <LanguagesIcon />
          中英双语
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
