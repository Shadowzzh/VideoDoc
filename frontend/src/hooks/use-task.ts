import { useEffect, useState } from "react"

import { getTask } from "@/lib/api"
import type { VideoTask } from "@/types"

export function useTask(taskId: string) {
  const [task, setTask] = useState<VideoTask | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [refreshVersion, setRefreshVersion] = useState(0)

  useEffect(() => {
    let active = true
    let timer: number | undefined

    const load = async () => {
      try {
        const value = await getTask(taskId)
        if (!active) {
          return
        }
        setTask(value)
        setError(null)
        // 补字幕这类后台动作不改任务状态，只看 status 会永远不刷新；
        // 任何步骤处于 running 都要继续轮询。
        const busy =
          value.status === "queued" ||
          value.status === "running" ||
          value.steps.some((step) => step.status === "running")
        if (busy) {
          timer = window.setTimeout(load, 1500)
        }
      } catch (reason) {
        if (active) {
          setError(reason instanceof Error ? reason.message : "任务加载失败")
          timer = window.setTimeout(load, 3000)
        }
      } finally {
        if (active) {
          setLoading(false)
        }
      }
    }

    void load()
    return () => {
      active = false
      if (timer !== undefined) {
        window.clearTimeout(timer)
      }
    }
  }, [taskId, refreshVersion])

  const refresh = () => setRefreshVersion((value) => value + 1)

  return { task, error, loading, refresh }
}
