import { AudioLinesIcon } from "lucide-react"
import { useEffect, useState } from "react"

import { toast } from "@/components/toast"
import { Button } from "@/components/ui/button"
import { addDub, getTask } from "@/lib/api"
import type { VideoTask } from "@/types"

interface DubButtonProps {
  task: VideoTask
  /** 完成后回调：结果页用它重新拉 result，播放器才会换上成片。 */
  onChanged?: () => void
  disabled?: boolean
}

type Phase = "idle" | "submitting" | "running" | "done" | "failed"

function phaseOf(task: VideoTask): Phase {
  const step = task.steps?.find((item) => item.key === "dub")
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
 * 「生成配音」按钮：中文配音 + 保留背景音乐 + 烧中文字幕。
 *
 * 和补字幕一样，配音不改变任务状态，所以按钮自己盯 ``dub`` 步骤：
 * 提交后显示已用时，完成/失败就地反映，刷新页面也能从后端状态恢复。
 */
export function DubButton({ task, onChanged, disabled }: DubButtonProps) {
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

  const run = async () => {
    setPhase("submitting")
    try {
      await addDub(task.id)
      toast("已提交：正在生成中文配音")
      setPhase("running")
    } catch (reason) {
      setPhase("failed")
      toast(reason instanceof Error ? reason.message : "生成配音失败", "error")
    }
  }

  let label = "生成配音"
  if (phase === "submitting") {
    label = "提交中…"
  } else if (phase === "running") {
    label = `配音中 ${elapsed}s`
  } else if (phase === "done") {
    label = "重新配音"
  } else if (phase === "failed") {
    label = "重试"
  }

  const busy = phase === "submitting" || phase === "running"

  return (
    <Button variant="outline" onClick={() => void run()} disabled={disabled || busy}>
      <AudioLinesIcon />
      {label}
    </Button>
  )
}
