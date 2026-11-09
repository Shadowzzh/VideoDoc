import { useEffect, useRef } from "react"

import { toast } from "@/components/toast"
import { taskTitle } from "@/lib/format"
import type { VideoTask } from "@/types"

/**
 * 全局字幕状态观察器：字幕生成完（或失败）时，无论用户停在哪个页面都弹一条提示。
 *
 * 数据来自 AppShell 已有的任务列表轮询，不额外发请求。
 * 中文素材的字幕 1 秒内就完成，5 秒轮询可能看不到 running，这种情况交给按钮自身显示；
 * 这里只处理能观察到 running 的较长任务。
 */
export function SubtitleWatcher({ tasks }: { tasks: VideoTask[] }) {
  const previous = useRef<Map<string, string>>(new Map())

  useEffect(() => {
    for (const task of tasks) {
      const step = task.steps?.find((item) => item.key === "subtitle")
      if (!step) {
        continue
      }
      const before = previous.current.get(task.id)
      if (before === "running") {
        if (step.error) {
          toast(`「${taskTitle(task)}」字幕生成失败`, "error")
        } else if (step.finished_at) {
          toast(`「${taskTitle(task)}」字幕已生成`)
        }
      }
      previous.current.set(task.id, step.status)
    }
  }, [tasks])

  return null
}
