import { useEffect, useState } from "react"

import { listTasks } from "@/lib/api"
import type { VideoTask } from "@/types"

export function useTasks(refreshMs = 5000) {
  const [tasks, setTasks] = useState<VideoTask[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let active = true
    let timer: number | undefined

    const load = async () => {
      try {
        const value = await listTasks()
        if (active) {
          setTasks(value)
          setError(null)
        }
      } catch (reason) {
        if (active) {
          setError(reason instanceof Error ? reason.message : "任务列表加载失败")
        }
      } finally {
        if (active) {
          setLoading(false)
          timer = window.setTimeout(load, refreshMs)
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
  }, [refreshMs])

  return { tasks, error, loading }
}
