import { useEffect, useState } from "react"

/**
 * 按固定间隔返回当前时间戳，用于让「运行中阶段已耗时」按秒走动。
 *
 * 只在 ``active`` 为真时计时：任务结束后必须停掉，否则页面会一直重渲染。
 */
export function useNow(active: boolean, interval = 1000): number {
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    if (!active) {
      return
    }
    setNow(Date.now())
    const timer = window.setInterval(() => setNow(Date.now()), interval)
    return () => window.clearInterval(timer)
  }, [active, interval])

  return now
}
