import {
  ArrowLeftIcon,
  BookOpenIcon,
  CaptionsIcon,
  ChevronRightIcon,
  ExternalLinkIcon,
  ListTreeIcon,
  ListChecksIcon,
  Maximize2Icon,
  Minimize2Icon,
  PauseIcon,
  PlayIcon,
  VideoIcon,
} from "lucide-react"
import { useCallback, useEffect, useLayoutEffect, useRef, useState, type MouseEvent, type RefObject } from "react"

import { AppShell } from "@/components/app-shell"
import { ErrorState } from "@/components/error-state"
import { FloatingVideoAssistant } from "@/components/floating-video-assistant"
import { SubtitleMenuButton } from "@/components/subtitle-menu-button"
import { Button } from "@/components/ui/button"
import { Card, CardHeader, CardTitle } from "@/components/ui/card"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet"
import { Skeleton } from "@/components/ui/skeleton"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { useMediaQuery } from "@/hooks/use-media-query"
import { useResult } from "@/hooks/use-result"
import { useTask } from "@/hooks/use-task"
import { mediaHref, taskHref } from "@/lib/api"
import { formatSeconds, resultTitle } from "@/lib/format"
import {
  INITIAL_FLOATING_VIDEO_MODE_STATE,
  enterFloatingVideoFullscreen,
  exitFloatingVideoFullscreen,
  hideFloatingVideo,
  revealFloatingVideo,
  toggleFloatingVideoSize,
  type FloatingVideoMode,
  type FloatingVideoModeState,
} from "@/lib/floating-video-window"
import { matchSectionAnchors, pickActiveSectionId } from "@/lib/outline-anchors"
import type { OutlineSection, VideoResult, VideoTask } from "@/types"

export function ResultPage({ taskId }: { taskId: string }) {
  const { result, error, loading, refresh: reload } = useResult(taskId)
  // 结果页也要能补字幕，所以额外拿一次任务（含 artifacts）。
  const taskState = useTask(taskId)

  // 字幕生成完要同时刷新任务状态和结果，播放器才会挂上新字幕轨。
  function handleSubtitleChanged() {
    taskState.refresh()
    reload()
  }
  const desktop = useMediaQuery("(min-width: 1024px)")
  const [videoModeState, setVideoModeState] = useState<FloatingVideoModeState>(INITIAL_FLOATING_VIDEO_MODE_STATE)
  const [videoPlaying, setVideoPlaying] = useState(false)
  const [mobileVideoOpen, setMobileVideoOpen] = useState(false)
  const [currentTime, setCurrentTime] = useState(0)
  const [activeView, setActiveView] = useState<"article" | "transcript">("article")
  const [articleScrollRequest, setArticleScrollRequest] = useState(0)
  const [readingSectionId, setReadingSectionId] = useState<string | null>(null)
  const videoRef = useRef<HTMLVideoElement | null>(null)
  // 浏览器全屏作用在浮窗内部元素上，由子组件把节点挂进来。
  const fullscreenElementRef = useRef<HTMLElement | null>(null)
  const articleRef = useRef<HTMLElement | null>(null)
  const pendingArticleSectionRef = useRef<string | null>(null)

  const playbackSection = findCurrentSection(result?.outline.sections || [], currentTime)
  // 文章视图的大纲高亮跟随阅读位置；视频浮窗和转写视图继续跟随播放进度。
  const outlineSectionId = activeView === "article" ? readingSectionId : playbackSection?.id ?? null

  useEffect(() => {
    const video = videoRef.current
    if (!video) {
      return
    }
    const updateTime = () => setCurrentTime(video.currentTime)
    const markPlaying = () => setVideoPlaying(true)
    const markPaused = () => setVideoPlaying(false)
    video.addEventListener("timeupdate", updateTime)
    video.addEventListener("play", markPlaying)
    video.addEventListener("pause", markPaused)
    video.addEventListener("ended", markPaused)
    return () => {
      video.removeEventListener("timeupdate", updateTime)
      video.removeEventListener("play", markPlaying)
      video.removeEventListener("pause", markPaused)
      video.removeEventListener("ended", markPaused)
    }
  }, [desktop, mobileVideoOpen, result])

  useEffect(() => {
    if (!result) {
      return
    }
    const previousTitle = document.title
    document.title = `${resultTitle(result)} · VideoDoc`
    return () => {
      document.title = previousTitle
    }
  }, [result])

  const togglePlayback = useCallback(() => {
    const video = videoRef.current
    if (!video) {
      return
    }
    if (video.paused) {
      setVideoModeState(revealFloatingVideo)
      void video.play().catch(() => undefined)
    } else {
      video.pause()
    }
  }, [])

  // V 每次只走一档：关闭 → 最大化 → 关闭；小窗 → 最大化 → 小窗；全屏 → 进入全屏前的档位。
  const toggleVideoSize = useCallback(() => {
    if (videoModeState.mode === "fullscreen") {
      void document.exitFullscreen().catch(() => undefined)
    }
    const next = toggleFloatingVideoSize(videoModeState)
    if (next.mode === "hidden" && videoModeState.mode === "maximized") {
      videoRef.current?.pause()
    }
    setVideoModeState(next)
  }, [videoModeState])

  const toggleVideoFullscreen = useCallback(() => {
    if (videoModeState.mode === "fullscreen") {
      void document.exitFullscreen().catch(() => undefined)
      setVideoModeState(exitFloatingVideoFullscreen)
      return
    }
    const element = fullscreenElementRef.current
    if (!element) {
      return
    }
    const previous = videoModeState
    setVideoModeState(enterFloatingVideoFullscreen)
    // 先让元素渲染为可见，再在用户手势仍然有效时请求浏览器全屏。
    window.requestAnimationFrame(() => {
      void element.requestFullscreen().catch(() => setVideoModeState(previous))
    })
  }, [videoModeState])

  // 显式「回到小窗」：按钮和 Esc 都用它。V 仍按「关闭 → 最大化 → 关闭」的循环走。
  const showVideoSmall = useCallback(() => {
    if (document.fullscreenElement) {
      void document.exitFullscreen().catch(() => undefined)
    }
    setVideoModeState((state) => (state.mode === "normal" ? state : { ...state, mode: "normal" }))
  }, [])

  // 顶栏和浮窗上的放大/缩小按钮：小窗 ↔ 最大化，从最大化/全屏回小窗，从关闭显示为小窗。
  const handleSizeButton = useCallback(() => {
    if (videoModeState.mode === "normal") {
      toggleVideoSize()
      return
    }
    showVideoSmall()
  }, [showVideoSmall, toggleVideoSize, videoModeState.mode])

  const hideVideo = useCallback(() => {
    videoRef.current?.pause()
    if (document.fullscreenElement) {
      void document.exitFullscreen().catch(() => undefined)
    }
    setVideoModeState(hideFloatingVideo)
  }, [])

  // 浏览器原生 Esc、F11 退出全屏时不经过按钮，这里把状态收敛回进入全屏前的档位。
  useEffect(() => {
    if (!desktop) {
      return
    }
    const handleFullscreenChange = () => {
      const element = fullscreenElementRef.current
      if (element && document.fullscreenElement === element) {
        return
      }
      setVideoModeState(exitFloatingVideoFullscreen)
    }
    document.addEventListener("fullscreenchange", handleFullscreenChange)
    return () => document.removeEventListener("fullscreenchange", handleFullscreenChange)
  }, [desktop])

  useEffect(() => {
    if (!desktop || !result) {
      return
    }
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.repeat || event.metaKey || event.ctrlKey || event.altKey || event.shiftKey) {
        return
      }
      if (event.code === "Space") {
        if (isSpaceShortcutBlockedTarget(event.target)) {
          return
        }
        event.preventDefault()
        const video = videoRef.current
        if (!video) {
          return
        }
        if (video.paused) {
          setVideoModeState(revealFloatingVideo)
          void video.play().catch(() => undefined)
        } else {
          video.pause()
        }
        return
      }
      if (isTextEditingTarget(event.target)) {
        return
      }
      if (event.code === "KeyV") {
        event.preventDefault()
        toggleVideoSize()
        return
      }
      if (event.code === "KeyF") {
        event.preventDefault()
        toggleVideoFullscreen()
        return
      }
      // 全屏时 Esc 由浏览器接管，不能再拦截，否则会和退出全屏冲突。
      if (event.key === "Escape" && !document.fullscreenElement) {
        event.preventDefault()
        setVideoModeState((state) => (state.mode === "maximized" ? { ...state, mode: "normal" } : state))
      }
    }
    window.addEventListener("keydown", handleKeyDown)
    return () => window.removeEventListener("keydown", handleKeyDown)
  }, [desktop, result, toggleVideoFullscreen, toggleVideoSize])

  const seekTo = (seconds: number, options: { autoPlay?: boolean } = {}) => {
    if (desktop) {
      setVideoModeState(revealFloatingVideo)
    } else {
      setMobileVideoOpen(true)
    }
    const autoPlay = options.autoPlay !== false
    window.setTimeout(() => {
      const video = videoRef.current
      if (!video) {
        return
      }
      const apply = () => {
        video.currentTime = seconds
        // 大纲跳转只在视频本来就在播放时继续播放，暂停状态下保持暂停。
        if (autoPlay || !video.paused) {
          void video.play().catch(() => undefined)
        }
      }
      if (video.readyState === 0) {
        video.addEventListener("loadedmetadata", apply, { once: true })
      } else {
        apply()
      }
    }, 0)
  }

  const selectOutlineSection = (section: OutlineSection) => {
    pendingArticleSectionRef.current = section.id
    setActiveView("article")
    setArticleScrollRequest((value) => value + 1)
    seekTo(section.start_sec, { autoPlay: false })
  }

  useLayoutEffect(() => {
    if (!result || activeView !== "article") {
      return
    }
    const sectionId = pendingArticleSectionRef.current
    if (!sectionId) {
      return
    }
    const article = articleRef.current
    if (!article) {
      return
    }
    const anchor = matchSectionAnchors(article, result.outline.sections).find((item) => item.id === sectionId)
    if (!anchor) {
      return
    }
    const anchorId = `article-${sectionId}`
    anchor.element.id = anchorId
    anchor.element.scrollIntoView({ behavior: "smooth", block: "start" })
    window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}#${anchorId}`)
    pendingArticleSectionRef.current = null
  }, [activeView, articleScrollRequest, result])

  // 文章滚动时的 scroll spy：把视口顶部所在的章节回写到左侧大纲。
  useEffect(() => {
    if (!result || activeView !== "article") {
      return
    }
    const article = articleRef.current
    if (!article) {
      return
    }
    const viewport = article.closest<HTMLElement>('[data-slot="scroll-area-viewport"]')
    if (!viewport) {
      return
    }
    const anchors = matchSectionAnchors(article, result.outline.sections)
    if (anchors.length === 0) {
      return
    }
    let frame = 0
    const measure = () => {
      frame = 0
      const viewportTop = viewport.getBoundingClientRect().top
      const line = Math.min(Math.max(viewport.clientHeight * 0.25, 120), 200)
      const scrollable = viewport.scrollHeight - viewport.clientHeight > 4
      const atBottom = scrollable && viewport.scrollTop + viewport.clientHeight >= viewport.scrollHeight - 4
      const positions = anchors.map((anchor) => ({ id: anchor.id, top: anchor.element.getBoundingClientRect().top }))
      setReadingSectionId(pickActiveSectionId(positions, { viewportTop, line, atBottom }))
    }
    const schedule = () => {
      if (frame === 0) {
        frame = window.requestAnimationFrame(measure)
      }
    }
    measure()
    const settle = window.setTimeout(measure, 500)
    viewport.addEventListener("scroll", schedule, { passive: true })
    window.addEventListener("resize", schedule)
    return () => {
      window.clearTimeout(settle)
      viewport.removeEventListener("scroll", schedule)
      window.removeEventListener("resize", schedule)
      if (frame !== 0) {
        window.cancelAnimationFrame(frame)
      }
    }
  }, [activeView, result])

  useLayoutEffect(() => {
    if (desktop && videoModeState.mode === "maximized") {
      videoRef.current?.focus({ preventScroll: true })
    }
  }, [desktop, videoModeState.mode])

  const handleArticleClick = (event: MouseEvent<HTMLElement>) => {
    const target = event.target
    if (!(target instanceof Element)) {
      return
    }
    const anchor = target.closest<HTMLAnchorElement>('a[href^="#t="]')
    if (!anchor) {
      return
    }
    event.preventDefault()
    seekTo(Number(anchor.getAttribute("href")?.slice(3) || 0))
  }

  if (loading) {
    return <AppShell activeTaskId={taskId}><ResultSkeleton /></AppShell>
  }
  if (error) {
    return <AppShell activeTaskId={taskId}><div className="p-6"><ErrorState message={error} /></div></AppShell>
  }
  if (!result) {
    return <AppShell activeTaskId={taskId} />
  }

  return (
    <AppShell
      activeTaskId={taskId}
      sidebarLabel="文章大纲"
      renderSidebar={(onNavigate) => (
        <ResultOutlineSidebar
          result={result}
          activeSectionId={outlineSectionId}
          onSelect={selectOutlineSection}
          onNavigate={onNavigate}
        />
      )}
    >
      <div className="flex h-full min-h-0 flex-col">
        <ResultHeader
          taskId={taskId}
          result={result}
          task={taskState.task}
          onChanged={handleSubtitleChanged}
          desktop={desktop}
          videoMode={videoModeState.mode}
          videoPlaying={videoPlaying}
          onTogglePlayback={togglePlayback}
          onToggleVideoSize={handleSizeButton}
          onOpenMobileVideo={() => setMobileVideoOpen(true)}
        />
        <div className="min-h-0 flex-1">
            <ReadingWorkspace
              result={result}
              activeView={activeView}
              articleRef={articleRef}
              onViewChange={setActiveView}
              onSeek={seekTo}
            onArticleClick={handleArticleClick}
          />
        </div>

        {desktop ? (
          <FloatingVideoAssistant
            taskId={taskId}
            result={result}
            currentSection={playbackSection}
            videoRef={videoRef}
            fullscreenElementRef={fullscreenElementRef}
            mode={videoModeState.mode}
            onToggleSize={handleSizeButton}
            onToggleFullscreen={toggleVideoFullscreen}
            onHide={hideVideo}
            subtitleVtt={result.subtitle_vtt}
          />
        ) : (
          <Sheet open={mobileVideoOpen} onOpenChange={setMobileVideoOpen}>
            <SheetContent side="bottom" className="max-h-[88vh] rounded-t-xl p-0">
              <SheetTitle className="sr-only">辅助视频</SheetTitle>
              <MobileVideoAssistant
                taskId={taskId}
                result={result}
                currentSection={playbackSection}
                videoRef={videoRef}
                subtitleVtt={result.subtitle_vtt}
              />
            </SheetContent>
          </Sheet>
        )}
      </div>
    </AppShell>
  )
}

interface ResultHeaderProps {
  taskId: string
  result: VideoResult
  task: VideoTask | null
  onChanged?: () => void
  desktop: boolean
  videoMode: FloatingVideoMode
  videoPlaying: boolean
  onTogglePlayback: () => void
  onToggleVideoSize: () => void
  onOpenMobileVideo: () => void
}

function ResultHeader({
  taskId,
  result,
  task,
  onChanged,
  desktop,
  videoMode,
  videoPlaying,
  onTogglePlayback,
  onToggleVideoSize,
  onOpenMobileVideo,
}: ResultHeaderProps) {
  let sizeLabel = "放大视频"
  let SizeIcon = Maximize2Icon
  if (videoMode === "maximized") {
    sizeLabel = "缩小视频"
    SizeIcon = Minimize2Icon
  } else if (videoMode === "fullscreen") {
    sizeLabel = "退出全屏"
    SizeIcon = Minimize2Icon
  } else if (videoMode === "hidden") {
    sizeLabel = "显示视频"
    SizeIcon = Maximize2Icon
  }
  let PlaybackIcon = PlayIcon
  let playbackLabel = "播放"
  if (videoPlaying) {
    PlaybackIcon = PauseIcon
    playbackLabel = "暂停"
  }
  return (
    <header className="flex shrink-0 items-center justify-between gap-4 border-b bg-background px-4 py-3 md:px-6">
      <div className="min-w-0">
        <div className="flex items-center gap-2 text-xs text-muted-foreground"><span>已完成任务</span><ChevronRightIcon className="size-3" /><span>文章</span></div>
        <h1 className="truncate text-lg font-semibold tracking-tight">{resultTitle(result)}</h1>
      </div>
      <div className="flex shrink-0 items-center gap-1">
        {task ? <SubtitleMenuButton task={task} onChanged={onChanged} /> : null}
        <Button nativeButton={false} variant="outline" size="sm" render={<a href={taskHref(taskId)} />}>
          <ListChecksIcon />处理流程
        </Button>
        {result.metadata.webpage_url ? (
          <Tooltip><TooltipTrigger render={<Button nativeButton={false} variant="ghost" size="icon" render={<a href={result.metadata.webpage_url} target="_blank" rel="noreferrer" />} />}><ExternalLinkIcon /><span className="sr-only">打开原链接</span></TooltipTrigger><TooltipContent>打开原链接</TooltipContent></Tooltip>
        ) : null}
        {desktop ? (
          <>
            <Button variant="outline" size="sm" onClick={onTogglePlayback}>
              <PlaybackIcon />
              {playbackLabel}
              <ShortcutKey>Space</ShortcutKey>
            </Button>
            <Button variant="outline" size="sm" onClick={onToggleVideoSize}>
              <SizeIcon />
              {sizeLabel}
              <ShortcutKey>V</ShortcutKey>
            </Button>
          </>
        ) : (
          <Button variant="outline" size="sm" onClick={onOpenMobileVideo}>
            <VideoIcon />查看视频
          </Button>
        )}
      </div>
    </header>
  )
}

function ShortcutKey({ children }: { children: string }) {
  return <kbd className="ml-1 rounded border bg-muted px-1 font-mono text-[10px] text-muted-foreground">{children}</kbd>
}

interface ReadingWorkspaceProps {
  result: VideoResult
  activeView: "article" | "transcript"
  articleRef: RefObject<HTMLElement | null>
  onViewChange: (value: "article" | "transcript") => void
  onSeek: (seconds: number) => void
  onArticleClick: (event: MouseEvent<HTMLElement>) => void
}

function ReadingWorkspace({
  result,
  activeView,
  articleRef,
  onViewChange,
  onSeek,
  onArticleClick,
}: ReadingWorkspaceProps) {
  const handleViewChange = (value: string) => {
    if (value === "article" || value === "transcript") {
      onViewChange(value)
    }
  }
  return (
    <div className="h-full min-h-0 bg-background">
      <Tabs value={activeView} onValueChange={handleViewChange} className="flex h-full flex-col gap-0">
        <div className="flex h-12 shrink-0 items-center border-b px-4 md:px-6">
          <TabsList>
            <TabsTrigger value="article"><BookOpenIcon />文章</TabsTrigger>
            <TabsTrigger value="transcript"><CaptionsIcon />转写</TabsTrigger>
          </TabsList>
        </div>
        <TabsContent value="article" className="min-h-0 flex-1 overflow-hidden">
          <ScrollArea className="h-full"><article ref={articleRef} className="article-content px-5 pb-72 pt-8 md:px-10 md:pb-72 md:pt-12" onClick={onArticleClick} dangerouslySetInnerHTML={{ __html: result.article_html }} /></ScrollArea>
        </TabsContent>
        <TabsContent value="transcript" className="min-h-0 flex-1 overflow-hidden">
          <ScrollArea className="h-full"><div className="max-w-4xl space-y-1 px-5 py-8 md:px-10">{result.segments.map((segment) => <button key={segment.id} type="button" onClick={() => onSeek(segment.start_sec)} className="grid w-full grid-cols-[4rem_1fr] gap-3 rounded-lg px-3 py-2.5 text-left hover:bg-accent"><span className="font-mono text-xs text-muted-foreground">{formatSeconds(segment.start_sec)}</span><span className="text-sm leading-6">{segment.text}</span></button>)}</div></ScrollArea>
        </TabsContent>
      </Tabs>
    </div>
  )
}

function ResultOutlineSidebar({
  result,
  activeSectionId,
  onSelect,
  onNavigate,
}: {
  result: VideoResult
  activeSectionId: string | null
  onSelect: (section: OutlineSection) => void
  onNavigate?: () => void
}) {
  const selectSection = (section: OutlineSection) => {
    onSelect(section)
    onNavigate?.()
  }
  return (
    <aside className="flex h-full min-h-0 w-full flex-col bg-sidebar text-sidebar-foreground">
      <div className="flex h-14 shrink-0 items-center border-b border-sidebar-border px-3">
        <Button nativeButton={false} variant="ghost" size="sm" render={<a href="/app/" onClick={onNavigate} />}>
          <ArrowLeftIcon />全部任务
        </Button>
      </div>
      <div className="space-y-1 border-b border-sidebar-border px-4 py-4">
        <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground"><ListTreeIcon className="size-3.5" />文章大纲</div>
        <p className="line-clamp-2 text-sm font-semibold leading-5 [overflow-wrap:anywhere]">{resultTitle(result)}</p>
      </div>
      <ScrollArea className="min-h-0 flex-1 px-2 py-3">
        <div className="space-y-1">
          {result.outline.sections.map((section, index) => {
            let className = "w-full rounded-lg px-3 py-2.5 text-left transition-colors hover:bg-sidebar-accent"
            if (activeSectionId === section.id) {
              className += " bg-sidebar-accent text-sidebar-accent-foreground"
            }
            return (
              <button key={section.id} type="button" className={className} onClick={() => selectSection(section)}>
                <div className="mb-1 flex items-center justify-between gap-2">
                  <span className="font-mono text-[10px] text-muted-foreground">{String(index + 1).padStart(2, "0")}</span>
                  <span className="font-mono text-[10px] text-muted-foreground">{section.start_time}</span>
                </div>
                <p className="text-sm font-medium leading-5 [overflow-wrap:anywhere]">{section.title}</p>
              </button>
            )
          })}
        </div>
      </ScrollArea>
    </aside>
  )
}

interface VideoAssistantProps {
  taskId: string
  result: VideoResult
  currentSection: OutlineSection | null
  videoRef: RefObject<HTMLVideoElement | null>
  subtitleVtt?: string | null
}

function MobileVideoAssistant({ taskId, result, currentSection, videoRef, subtitleVtt }: VideoAssistantProps) {
  return (
    <aside className="bg-background p-4 pt-12">
      <Card className="gap-4 overflow-hidden py-0">
        <video ref={videoRef} tabIndex={0} controls preload="metadata" src={mediaHref(taskId, result.video)} className="aspect-video w-full bg-black object-contain">
          {subtitleVtt ? (
            <track kind="subtitles" srcLang="zh" label="中文" src={mediaHref(taskId, subtitleVtt)} default />
          ) : null}
        </video>
        <CardHeader className="pb-4">
          <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground"><VideoIcon className="size-3.5" />辅助视频</div>
          <CardTitle className="text-base leading-6">{currentSection?.title || "等待播放"}</CardTitle>
          <p className="font-mono text-xs text-muted-foreground">{currentSection ? `${currentSection.start_time}–${currentSection.end_time}` : "点击文章、大纲或转写中的时间位置"}</p>
        </CardHeader>
      </Card>
    </aside>
  )
}

function isTextEditingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) {
    return false
  }
  return target.isContentEditable || target.closest("input, textarea, select") !== null
}

function isSpaceShortcutBlockedTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) {
    return false
  }
  if (isTextEditingTarget(target)) {
    return true
  }
  return target.closest("button, a[href], video, [role='button'], [role='link']") !== null
}

function findCurrentSection(sections: OutlineSection[], currentTime: number): OutlineSection | null {
  return sections.find((section) => currentTime >= section.start_sec && currentTime <= section.end_sec) || null
}

function ResultSkeleton() {
  return <div className="space-y-4 p-6"><Skeleton className="h-10 w-2/3" /><Skeleton className="h-[70vh]" /></div>
}
