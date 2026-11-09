import { CaptionsIcon, LanguagesIcon } from "lucide-react"
import { useEffect, useState } from "react"

import { toast } from "@/components/toast"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { addSubtitle, getTask } from "@/lib/api"
import type { VideoTask } from "@/types"

interface SubtitleMenuButtonProps {
  task: VideoTask
  /** 状态变化后回调：结果页用它重新拉 result，播放器才会挂上新字幕轨。 */
  onChanged?: () => void
  disabled?: boolean
}

type Phase = "idle" | "submitting" | "running" | "done" | "failed"

function phaseOf(task: VideoTask): Phase {
  const step = task.steps?.find((item) => item.key === "subtitle")
  if (!step) {
    return "idle"
  }
  if (step.status === "running") {
    return "running"
  }
  if (step.error) {
    return "failed"
  }
  if (step.finished_at && step.status !== "pending") {
    return "done"
  }
  return "idle"
}

/**
 * 显式的「生成字幕」按钮：任务详情页和结果页都放一个。
 *
 * 补字幕不改变任务状态，所以按钮必须自己盯着 subtitle 步骤：
 * 提交后显示已用时，完成/失败就地反映，刷新页面后也能从后端状态恢复。
 */
function hasMode(task: VideoTask, mode: "zh" | "bilingual"): boolean {
  const artifacts = task.artifacts ?? {}
  if (artifacts[`subtitle_${mode}_vtt`]) {
    return true
  }
  // 迁移前只有无前缀产物，按任务记录的模式归属。
  if (artifacts["subtitle_vtt"] && (task.subtitle_mode ?? "zh") === mode) {
    return true
  }
  return false
}

export function SubtitleMenuButton({ task, onChanged, disabled }: SubtitleMenuButtonProps) {
  const [phase, setPhase] = useState<Phase>(() => phaseOf(task))
  const [startedAt, setStartedAt] = useState<number | null>(null)
  const [elapsed, setElapsed] = useState(0)

  useEffect(() => {
    setPhase(phaseOf(task))
  }, [task])

  useEffect(() => {
    if (phase !== "running") {
      setStartedAt(null)
      setElapsed(0)
      return
    }
    setStartedAt((previous) => previous ?? Date.now())
  }, [phase])

  useEffect(() => {
    if (startedAt === null) {
      return
    }
    const timer = window.setInterval(() => {
      setElapsed(Math.floor((Date.now() - startedAt) / 1000))
    }, 1000)
    return () => window.clearInterval(timer)
  }, [startedAt])

  useEffect(() => {
    if (phase !== "running") {
      return
    }
    let active = true
    const timer = window.setInterval(async () => {
      try {
        const fresh = await getTask(task.id)
        if (!active) {
          return
        }
        const next = phaseOf(fresh)
        setPhase(next)
        if (next !== "running") {
          window.clearInterval(timer)
          onChanged?.()
        }
      } catch {
        // 单次轮询失败不改变状态，下一轮再试。
      }
    }, 2000)
    return () => {
      active = false
      window.clearInterval(timer)
    }
  }, [phase, task.id, onChanged])

  if (!task.artifacts?.transcript_segments) {
    return null
  }

  const run = async (mode: "zh" | "bilingual") => {
    setPhase("submitting")
    try {
      await addSubtitle(task.id, mode)
      toast(mode === "zh" ? "已提交：正在生成中文字幕" : "已提交：正在生成中英字幕")
      setPhase("running")
      onChanged?.()
    } catch (reason) {
      setPhase("failed")
      toast(reason instanceof Error ? reason.message : "补字幕失败", "error")
    }
  }

  let label = "生成字幕"
  if (phase === "submitting") {
    label = "提交中…"
  } else if (phase === "running") {
    label = `生成中 ${elapsed}s`
  } else if (phase === "done") {
    label = "已生成"
  } else if (phase === "failed") {
    label = "重试"
  }

  const busy = phase === "submitting" || phase === "running"

  return (
    <DropdownMenu>
      <DropdownMenuTrigger render={<Button variant="outline" disabled={disabled || busy} />}>
        <CaptionsIcon />
        {label}
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuItem onClick={() => void run("zh")}>
          <CaptionsIcon />
          中文字幕
          {hasMode(task, "zh") ? <span className="ml-auto text-xs text-muted-foreground">已有</span> : null}
        </DropdownMenuItem>
        <DropdownMenuItem onClick={() => void run("bilingual")}>
          <LanguagesIcon />
          中英双语
          {hasMode(task, "bilingual") ? <span className="ml-auto text-xs text-muted-foreground">已有</span> : null}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
