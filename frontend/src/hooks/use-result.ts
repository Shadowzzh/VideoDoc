import { useEffect, useState } from "react"

import { getResult } from "@/lib/api"
import type { VideoResult } from "@/types"

export function useResult(taskId: string) {
  const [result, setResult] = useState<VideoResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [refreshVersion, setRefreshVersion] = useState(0)

  useEffect(() => {
    let active = true
    getResult(taskId)
      .then((value) => {
        if (active) {
          setResult(value)
          setError(null)
        }
      })
      .catch((reason) => {
        if (active) {
          setError(reason instanceof Error ? reason.message : "结果加载失败")
        }
      })
      .finally(() => {
        if (active) {
          setLoading(false)
        }
      })
    return () => {
      active = false
    }
  }, [taskId, refreshVersion])

  // 字幕生成完要重新拉结果，播放器才会挂上新的字幕轨。
  function refresh() {
    setRefreshVersion((value) => value + 1)
  }

  return { result, error, loading, refresh }
}
