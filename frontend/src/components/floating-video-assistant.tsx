import {
  GripHorizontalIcon,
  Maximize2Icon,
  Minimize2Icon,
  VideoIcon,
  XIcon,
} from "lucide-react"
import { useEffect, useState, type RefObject } from "react"
import { Rnd } from "react-rnd"

import { Button } from "@/components/ui/button"
import { Card, CardHeader, CardTitle } from "@/components/ui/card"
import { mediaHref } from "@/lib/api"
import {
  FLOATING_VIDEO_ASPECT_RATIO,
  FLOATING_VIDEO_FOOTER_HEIGHT,
  clampFloatingVideoRect,
  defaultFloatingVideoRect,
  floatingVideoHeight,
  floatingVideoWidthLimits,
  decodeFloatingVideoRect,
  maximizedFloatingVideoRect,
  type FloatingVideoRect,
  type PersistedFloatingVideoRect,
  type ViewportSize,
} from "@/lib/floating-video-window"
import { cn } from "@/lib/utils"
import type { OutlineSection, VideoResult } from "@/types"

export const FLOATING_VIDEO_STORAGE_KEY = "videodoc-floating-video-rect-v1"

interface FloatingVideoAssistantProps {
  taskId: string
  result: VideoResult
  currentSection: OutlineSection | null
  videoRef: RefObject<HTMLVideoElement | null>
  visible: boolean
  expanded: boolean
  onToggleSize: () => void
  onHide: () => void
}

export function FloatingVideoAssistant({
  taskId,
  result,
  currentSection,
  videoRef,
  visible,
  expanded,
  onToggleSize,
  onHide,
}: FloatingVideoAssistantProps) {
  const [viewport, setViewport] = useState(readViewportSize)
  const [floatingRect, setFloatingRect] = useState(() => readStoredRect(readViewportSize()))

  useEffect(() => {
    const handleResize = () => {
      const nextViewport = readViewportSize()
      setViewport(nextViewport)
      setFloatingRect((current) => clampFloatingVideoRect(current, nextViewport))
    }
    window.addEventListener("resize", handleResize)
    return () => window.removeEventListener("resize", handleResize)
  }, [])

  useEffect(() => {
    try {
      window.localStorage.setItem(FLOATING_VIDEO_STORAGE_KEY, JSON.stringify(floatingRect))
    } catch {
      // localStorage may be unavailable in privacy-restricted browser contexts.
    }
  }, [floatingRect])

  const rect = expanded ? maximizedFloatingVideoRect(viewport) : floatingRect
  const limits = floatingVideoWidthLimits(viewport)
  const resizeEnabled = visible && !expanded
  let sizeLabel = "放大视频"
  let SizeIcon = Maximize2Icon
  if (expanded) {
    sizeLabel = "缩小视频"
    SizeIcon = Minimize2Icon
  }

  return (
    <div className="pointer-events-none fixed inset-0 z-40" aria-hidden={!visible}>
      {visible && expanded ? (
        <button
          type="button"
          aria-label="缩小视频遮罩"
          className="pointer-events-auto absolute inset-0 bg-black/55 backdrop-blur-xs"
          onClick={onToggleSize}
        />
      ) : null}
      <Rnd
        bounds="parent"
        position={{ x: rect.x, y: rect.y }}
        size={{ width: rect.width, height: rect.height }}
        minWidth={limits.minWidth}
        minHeight={floatingVideoHeight(limits.minWidth)}
        maxWidth={limits.maxWidth}
        maxHeight={floatingVideoHeight(limits.maxWidth)}
        lockAspectRatio={FLOATING_VIDEO_ASPECT_RATIO}
        lockAspectRatioExtraHeight={FLOATING_VIDEO_FOOTER_HEIGHT}
        dragHandleClassName="video-drag-handle"
        disableDragging={!resizeEnabled}
        enableResizing={resizeEnabled}
        onDragStop={(_event, position) => {
          setFloatingRect((current) => clampFloatingVideoRect({
            ...current,
            x: position.x,
            y: position.y,
          }, viewport))
        }}
        onResizeStop={(_event, _direction, element, _delta, position) => {
          setFloatingRect(clampFloatingVideoRect({
            x: position.x,
            y: position.y,
            width: element.offsetWidth,
            height: element.offsetHeight,
          }, viewport))
        }}
        className={cn(
          "pointer-events-auto z-[1]",
          !visible && "invisible pointer-events-none opacity-0",
        )}
      >
        <aside className="h-full w-full" aria-label="视频浮窗">
          <Card className="h-full gap-0 overflow-hidden py-0 shadow-2xl ring-foreground/20">
            <div className="relative h-[calc(100%-4.5rem)] bg-black">
              <video
                ref={videoRef}
                tabIndex={0}
                controls
                preload="metadata"
                src={mediaHref(taskId, result.video)}
                className="h-full w-full bg-black object-contain"
              />
              <div className="absolute right-2 top-2 flex gap-1">
                <Button type="button" variant="secondary" size="icon" aria-label={sizeLabel} onClick={onToggleSize}>
                  <SizeIcon />
                </Button>
                <Button type="button" variant="secondary" size="icon" aria-label="隐藏视频" onClick={onHide}>
                  <XIcon />
                </Button>
              </div>
            </div>
            <CardHeader
              className="video-drag-handle h-[4.5rem] cursor-grab select-none gap-1 py-3 active:cursor-grabbing"
              title="拖动视频浮窗"
            >
              <div className="flex items-center justify-between gap-3">
                <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
                  <GripHorizontalIcon className="size-3.5" />
                  <VideoIcon className="size-3.5" />
                  视频浮窗
                </div>
                <div className="flex items-center gap-1">
                  <ShortcutKey>Space</ShortcutKey>
                  <span className="text-[10px] text-muted-foreground">播放</span>
                  <ShortcutKey>V</ShortcutKey>
                  <span className="text-[10px] text-muted-foreground">缩放</span>
                </div>
              </div>
              <CardTitle className="truncate text-sm leading-5">{currentSection?.title || "等待播放"}</CardTitle>
            </CardHeader>
          </Card>
        </aside>
      </Rnd>
    </div>
  )
}

function ShortcutKey({ children }: { children: string }) {
  return <kbd className="ml-1 rounded border bg-muted px-1 font-mono text-[10px] text-muted-foreground">{children}</kbd>
}

function readViewportSize(): ViewportSize {
  return {
    width: window.innerWidth,
    height: window.innerHeight,
  }
}

function readStoredRect(viewport: ViewportSize): FloatingVideoRect {
  try {
    const parsed: unknown = JSON.parse(window.localStorage.getItem(FLOATING_VIDEO_STORAGE_KEY) || "null")
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      const storedRect = decodeFloatingVideoRect(parsed as PersistedFloatingVideoRect)
      if (storedRect) {
        return clampFloatingVideoRect(storedRect, viewport)
      }
    }
  } catch {
    // Ignore invalid or inaccessible persisted state and use the default placement.
  }
  return defaultFloatingVideoRect(viewport)
}
