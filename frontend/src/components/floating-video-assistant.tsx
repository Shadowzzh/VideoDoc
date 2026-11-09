import {
  ExpandIcon,
  GripHorizontalIcon,
  Maximize2Icon,
  Minimize2Icon,
  ShrinkIcon,
  VideoIcon,
  XIcon,
} from "lucide-react"
import { useEffect, useRef, useState, type RefObject } from "react"
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
  type FloatingVideoMode,
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
  /** 全屏元素挂在 floating-video-assistant 内部，由结果页触发浏览器全屏。 */
  fullscreenElementRef: RefObject<HTMLElement | null>
  mode: FloatingVideoMode
  onToggleSize: () => void
  onToggleFullscreen: () => void
  onHide: () => void
  subtitleVtt?: string | null
}

export function FloatingVideoAssistant({
  taskId,
  result,
  currentSection,
  videoRef,
  fullscreenElementRef,
  mode,
  onToggleSize,
  onToggleFullscreen,
  onHide,
  subtitleVtt,
}: FloatingVideoAssistantProps) {
  const [viewport, setViewport] = useState(readViewportSize)
  const [floatingRect, setFloatingRect] = useState(() => readStoredRect(readViewportSize()))
  const asideRef = useRef<HTMLElement | null>(null)

  const visible = mode !== "hidden"
  const fullscreen = mode === "fullscreen"
  const expanded = mode === "maximized" || fullscreen

  useEffect(() => {
    fullscreenElementRef.current = asideRef.current
    return () => {
      if (fullscreenElementRef.current === asideRef.current) {
        fullscreenElementRef.current = null
      }
    }
  }, [fullscreenElementRef])

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
  const resizeEnabled = visible && mode === "normal"
  let sizeLabel = "放大视频"
  let SizeIcon = Maximize2Icon
  let fullscreenLabel = "全屏视频"
  let FullscreenIcon = ExpandIcon
  if (mode === "maximized") {
    sizeLabel = "缩小视频"
    SizeIcon = Minimize2Icon
  }
  if (fullscreen) {
    sizeLabel = "缩小视频"
    SizeIcon = Minimize2Icon
    fullscreenLabel = "退出全屏"
    FullscreenIcon = ShrinkIcon
  }

  return (
    <div className="pointer-events-none fixed inset-0 z-40" aria-hidden={!visible}>
      {visible && mode === "maximized" ? (
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
        <aside
          ref={asideRef}
          className={cn("h-full w-full bg-black", fullscreen && "flex flex-col")}
          aria-label="视频浮窗"
        >
          <Card
            className={cn(
              "h-full gap-0 overflow-hidden py-0 shadow-2xl ring-foreground/20",
              fullscreen && "rounded-none shadow-none ring-0",
            )}
          >
            <div className={cn("relative bg-black", fullscreen ? "h-full" : "h-[calc(100%-4.5rem)]")}>
              <video
                ref={videoRef}
                tabIndex={0}
                controls
                preload="metadata"
                src={mediaHref(taskId, result.video)}
                className="h-full w-full bg-black object-contain"
              >
                {subtitleVtt ? (
                  <track kind="subtitles" srcLang="zh" label="中文" src={mediaHref(taskId, subtitleVtt)} default />
                ) : null}
              </video>
              <div className="absolute right-2 top-2 flex gap-1">
                <Button type="button" variant="secondary" size="icon" aria-label={sizeLabel} onClick={onToggleSize}>
                  <SizeIcon />
                </Button>
                <Button type="button" variant="secondary" size="icon" aria-label={fullscreenLabel} onClick={onToggleFullscreen}>
                  <FullscreenIcon />
                </Button>
                <Button type="button" variant="secondary" size="icon" aria-label="隐藏视频" onClick={onHide}>
                  <XIcon />
                </Button>
              </div>
            </div>
            <CardHeader
              className={cn(
                "video-drag-handle h-[4.5rem] shrink-0 cursor-grab select-none gap-1 py-3 active:cursor-grabbing",
                fullscreen && "hidden",
              )}
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
                  <ShortcutKey>F</ShortcutKey>
                  <span className="text-[10px] text-muted-foreground">全屏</span>
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
