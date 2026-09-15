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
        if (value.status === "queued" || value.status === "running") {
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
