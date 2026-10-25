import { CircleStopIcon } from "lucide-react"
import { useState } from "react"

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogMedia,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { cancelTask } from "@/lib/api"
import { taskTitle, taskTitleShort } from "@/lib/format"
import type { VideoTask } from "@/types"

interface CancelTaskDialogProps {
  task: VideoTask
  open: boolean
  onOpenChange: (open: boolean) => void
  onCancelled: () => void
}

/**
 * 终止任务确认框。
 *
 * 单独抽出来是因为它有两个入口（任务卡片的操作菜单、任务页头部的按钮），而两处都要
 * 同一套确认文案和错误处理 —— 复制两份必然会漂移。
 *
 * 语义上强调「保留产物」：用户怕的是点了终止之后视频要重新下载、Whisper 要重跑一遍。
 */
export function CancelTaskDialog({ task, open, onOpenChange, onCancelled }: CancelTaskDialogProps) {
  const [cancelling, setCancelling] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleCancel = async () => {
    setCancelling(true)
    setError(null)
    try {
      await cancelTask(task.id)
      onOpenChange(false)
      onCancelled()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "终止任务失败")
    } finally {
      setCancelling(false)
    }
  }

  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogMedia className="bg-muted text-foreground">
            <CircleStopIcon />
          </AlertDialogMedia>
          <AlertDialogTitle>终止这个任务？</AlertDialogTitle>
          <AlertDialogDescription>
            “{taskTitleShort(task)}”会停止当前阶段的命令，已完成的视频、音频、转写、关键帧等产物全部保留。
            任务变成“已取消”，之后可以从最近的有效阶段继续，不会重新下载或重新转写。
          </AlertDialogDescription>
        </AlertDialogHeader>

        {error ? <p className="text-xs text-destructive">{error}</p> : null}

        <AlertDialogFooter>
          <AlertDialogCancel disabled={cancelling}>继续运行</AlertDialogCancel>
          <AlertDialogAction disabled={cancelling} onClick={() => void handleCancel()}>
            {cancelling ? "正在终止…" : "终止任务"}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
