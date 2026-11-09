import { useEffect, useState } from "react"
import { cn } from "cn"

/**
 * 极简全局提示：补字幕这类后台动作本身不改变任务状态，
 * 页面不刷新时用户会以为「点了没反应」。这里给一条即时反馈。
 */

export interface ToastMessage {
  id: number
  text: string
  tone: "info" | "error"
}

type Listener = (message: ToastMessage) => void

const listeners = new Set<Listener>()
let nextId = 1

export function toast(text: string, tone: "info" | "error" = "info"): void {
  const message: ToastMessage = { id: nextId++, text, tone }
  listeners.forEach((listener) => listener(message))
}

export function Toaster() {
  const [items, setItems] = useState<ToastMessage[]>([])

  useEffect(() => {
    const listener: Listener = (message) => {
      setItems((current) => [...current, message])
      window.setTimeout(() => {
        setItems((current) => current.filter((item) => item.id !== message.id))
      }, 4000)
    }
    listeners.add(listener)
    return () => {
      listeners.delete(listener)
    }
  }, [])

  if (items.length === 0) {
    return null
  }

  return (
    <div
      aria-live="polite"
      role="status"
      className="pointer-events-none fixed inset-x-0 bottom-4 z-60 flex flex-col items-center gap-2 px-4"
    >
      {items.map((item) => (
        <div
          key={item.id}
          className={cn(
            "pointer-events-auto max-w-md rounded-md border px-4 py-2 text-sm shadow-lg",
            item.tone === "error"
              ? "border-destructive/40 bg-destructive text-white"
              : "bg-popover text-popover-foreground",
          )}
        >
          {item.text}
        </div>
      ))}
    </div>
  )
}
