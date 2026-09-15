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
  XIcon,
} from "lucide-react"
import { useEffect, useLayoutEffect, useRef, useState, type MouseEvent, type RefObject } from "react"

import { AppShell } from "@/components/app-shell"
import { ErrorState } from "@/components/error-state"
import { Button } from "@/components/ui/button"
import { Card, CardHeader, CardTitle } from "@/components/ui/card"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet"
import { Skeleton } from "@/components/ui/skeleton"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { useMediaQuery } from "@/hooks/use-media-query"
import { useResult } from "@/hooks/use-result"
import { mediaHref, taskHref } from "@/lib/api"
import { formatSeconds, resultTitle } from "@/lib/format"
import type { OutlineSection, VideoResult } from "@/types"

export function ResultPage({ taskId }: { taskId: string }) {
  const { result, error, loading } = useResult(taskId)
  const desktop = useMediaQuery("(min-width: 1024px)")
  const [videoVisible, setVideoVisible] = useState(true)
  const [videoExpanded, setVideoExpanded] = useState(false)
  const [videoPlaying, setVideoPlaying] = useState(false)
  const [mobileVideoOpen, setMobileVideoOpen] = useState(false)
  const [currentTime, setCurrentTime] = useState(0)
  const [activeView, setActiveView] = useState<"article" | "transcript">("article")
  const [articleScrollRequest, setArticleScrollRequest] = useState(0)
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const articleRef = useRef<HTMLElement | null>(null)
  const pendingArticleSectionRef = useRef<string | null>(null)

  const currentSection = findCurrentSection(result?.outline.sections || [], currentTime)

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

  const togglePlayback = () => {
    const video = videoRef.current
    if (!video) {
      return
    }
    if (video.paused) {
      setVideoVisible(true)
      void video.play().catch(() => undefined)
    } else {
      video.pause()
    }
  }

  const toggleVideoSize = () => {
    if (!videoVisible) {
      setVideoVisible(true)
      setVideoExpanded(false)
      return
    }
    setVideoVisible(true)
    setVideoExpanded((value) => !value)
  }

  const hideVideo = () => {
    videoRef.current?.pause()
    setVideoExpanded(false)
    setVideoVisible(false)
  }

  useEffect(() => {
    if (!desktop || !result) {
      return
    }
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.repeat || event.metaKey || event.ctrlKey || event.altKey || event.shiftKey) {
        return
      }
      if (isEditableTarget(event.target)) {
        return
      }
      if (event.code === "KeyK") {
        event.preventDefault()
        const video = videoRef.current
        if (!video) {
          return
        }
        if (video.paused) {
          setVideoVisible(true)
          void video.play().catch(() => undefined)
        } else {
          video.pause()
        }
        return
      }
      if (event.code === "KeyV") {
        event.preventDefault()
        if (!videoVisible) {
          setVideoVisible(true)
          setVideoExpanded(false)
          return
        }
        setVideoVisible(true)
        setVideoExpanded((value) => !value)
        return
      }
      if (event.key === "Escape" && videoExpanded) {
        event.preventDefault()
        setVideoExpanded(false)
      }
    }
    window.addEventListener("keydown", handleKeyDown)
    return () => window.removeEventListener("keydown", handleKeyDown)
  }, [desktop, result, videoExpanded, videoVisible])

  const seekTo = (seconds: number) => {
    if (desktop) {
      setVideoVisible(true)
    } else {
      setMobileVideoOpen(true)
    }
    window.setTimeout(() => {
      const video = videoRef.current
      if (!video) {
        return
      }
      const apply = () => {
        video.currentTime = seconds
        void video.play().catch(() => undefined)
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
    seekTo(section.start_sec)
  }

  useLayoutEffect(() => {
    if (!result || activeView !== "article") {
      return
    }
    const sectionId = pendingArticleSectionRef.current
    if (!sectionId) {
      return
    }
    const sectionIndex = result.outline.sections.findIndex((section) => section.id === sectionId)
    if (sectionIndex < 0) {
      return
    }
    const headings = articleRef.current?.querySelectorAll("h2")
    const heading = headings?.item(sectionIndex)
    if (!heading) {
      return
    }
    const anchorId = `article-${sectionId}`
    heading.id = anchorId
    heading.scrollIntoView({ behavior: "smooth", block: "start" })
    window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}#${anchorId}`)
    pendingArticleSectionRef.current = null
  }, [activeView, articleScrollRequest, result])

  useLayoutEffect(() => {
    if (desktop && videoVisible && videoExpanded) {
      videoRef.current?.focus({ preventScroll: true })
    }
  }, [desktop, videoExpanded, videoVisible])

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
          currentSection={currentSection}
          onSelect={selectOutlineSection}
          onNavigate={onNavigate}
        />
      )}
    >
      <div className="flex h-full min-h-0 flex-col">
        <ResultHeader
          taskId={taskId}
          result={result}
          desktop={desktop}
          videoVisible={videoVisible}
          videoExpanded={videoExpanded}
          videoPlaying={videoPlaying}
          onTogglePlayback={togglePlayback}
          onToggleVideoSize={toggleVideoSize}
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
            currentSection={currentSection}
            videoRef={videoRef}
            visible={videoVisible}
            expanded={videoExpanded}
            onToggleSize={toggleVideoSize}
            onHide={hideVideo}
          />
        ) : (
          <Sheet open={mobileVideoOpen} onOpenChange={setMobileVideoOpen}>
            <SheetContent side="bottom" className="max-h-[88vh] rounded-t-xl p-0">
              <SheetTitle className="sr-only">辅助视频</SheetTitle>
              <MobileVideoAssistant
                taskId={taskId}
                result={result}
                currentSection={currentSection}
                videoRef={videoRef}
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
  desktop: boolean
  videoVisible: boolean
  videoExpanded: boolean
  videoPlaying: boolean
  onTogglePlayback: () => void
  onToggleVideoSize: () => void
  onOpenMobileVideo: () => void
}

function ResultHeader({
  taskId,
  result,
  desktop,
  videoVisible,
  videoExpanded,
  videoPlaying,
  onTogglePlayback,
  onToggleVideoSize,
  onOpenMobileVideo,
}: ResultHeaderProps) {
  let sizeLabel = "放大视频"
  let SizeIcon = Maximize2Icon
  if (videoExpanded) {
    sizeLabel = "缩小视频"
    SizeIcon = Minimize2Icon
  }
  let PlaybackIcon = PlayIcon
  let playbackLabel = "播放"
  if (videoPlaying) {
    PlaybackIcon = PauseIcon
    playbackLabel = "暂停"
  }
  let videoSizeLabel = sizeLabel
  if (!videoVisible) {
    videoSizeLabel = "显示视频"
  }
  return (
    <header className="flex shrink-0 items-center justify-between gap-4 border-b bg-background px-4 py-3 md:px-6">
      <div className="min-w-0">
        <div className="flex items-center gap-2 text-xs text-muted-foreground"><span>已完成任务</span><ChevronRightIcon className="size-3" /><span>文章</span></div>
        <h1 className="truncate text-lg font-semibold tracking-tight">{resultTitle(result)}</h1>
      </div>
      <div className="flex shrink-0 items-center gap-1">
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
              <ShortcutKey>K</ShortcutKey>
            </Button>
            <Button variant="outline" size="sm" onClick={onToggleVideoSize}>
              <SizeIcon />
              {videoSizeLabel}
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
          <ScrollArea className="h-full"><div className="mx-auto max-w-4xl space-y-1 px-5 py-8 md:px-10">{result.segments.map((segment) => <button key={segment.id} type="button" onClick={() => onSeek(segment.start_sec)} className="grid w-full grid-cols-[4rem_1fr] gap-3 rounded-lg px-3 py-2.5 text-left hover:bg-accent"><span className="font-mono text-xs text-muted-foreground">{formatSeconds(segment.start_sec)}</span><span className="text-sm leading-6">{segment.text}</span></button>)}</div></ScrollArea>
        </TabsContent>
      </Tabs>
    </div>
  )
}

function ResultOutlineSidebar({
  result,
  currentSection,
  onSelect,
  onNavigate,
}: {
  result: VideoResult
  currentSection: OutlineSection | null
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
        <p className="line-clamp-2 text-sm font-semibold leading-5">{resultTitle(result)}</p>
      </div>
      <ScrollArea className="min-h-0 flex-1 px-2 py-3">
        <div className="space-y-1">
          {result.outline.sections.map((section, index) => {
            let className = "w-full rounded-lg px-3 py-2.5 text-left transition-colors hover:bg-sidebar-accent"
            if (currentSection?.id === section.id) {
              className += " bg-sidebar-accent text-sidebar-accent-foreground"
            }
            return (
              <button key={section.id} type="button" className={className} onClick={() => selectSection(section)}>
                <div className="mb-1 flex items-center justify-between gap-2">
                  <span className="font-mono text-[10px] text-muted-foreground">{String(index + 1).padStart(2, "0")}</span>
                  <span className="font-mono text-[10px] text-muted-foreground">{section.start_time}</span>
                </div>
                <p className="text-sm font-medium leading-5">{section.title}</p>
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
}

function FloatingVideoAssistant({
  taskId,
  result,
  currentSection,
  videoRef,
  visible,
  expanded,
  onToggleSize,
  onHide,
}: VideoAssistantProps & {
  visible: boolean
  expanded: boolean
  onToggleSize: () => void
  onHide: () => void
}) {
  let containerClass = "fixed bottom-4 right-4 z-40 w-[min(22.5rem,calc(100vw-2rem))] transition-all duration-200"
  if (expanded) {
    containerClass = "fixed left-1/2 top-1/2 z-50 w-[min(72rem,calc(100vw-3rem))] -translate-x-1/2 -translate-y-1/2 transition-all duration-200"
  }
  if (!visible) {
    containerClass += " invisible pointer-events-none opacity-0"
  }
  let sizeLabel = "放大视频"
  let SizeIcon = Maximize2Icon
  if (expanded) {
    sizeLabel = "缩小视频"
    SizeIcon = Minimize2Icon
  }
  return (
    <>
      {visible && expanded ? <button type="button" aria-label="缩小视频遮罩" className="fixed inset-0 z-40 bg-black/55 backdrop-blur-xs" onClick={onToggleSize} /> : null}
      <aside className={containerClass} aria-label="视频浮窗">
        <Card className="gap-0 overflow-hidden py-0 shadow-2xl ring-foreground/20">
          <div className="relative bg-black">
            <video
              ref={videoRef}
              tabIndex={0}
              controls
              preload="metadata"
              src={mediaHref(taskId, result.video)}
              className="aspect-video max-h-[calc(100vh-10rem)] w-full bg-black object-contain"
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
          <CardHeader className="gap-1 py-3">
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground"><VideoIcon className="size-3.5" />视频浮窗</div>
              <div className="flex items-center gap-1"><ShortcutKey>K</ShortcutKey><span className="text-[10px] text-muted-foreground">播放</span><ShortcutKey>V</ShortcutKey><span className="text-[10px] text-muted-foreground">缩放</span></div>
            </div>
            <CardTitle className="truncate text-sm leading-5">{currentSection?.title || "等待播放"}</CardTitle>
          </CardHeader>
        </Card>
      </aside>
    </>
  )
}

function MobileVideoAssistant({ taskId, result, currentSection, videoRef }: VideoAssistantProps) {
  return (
    <aside className="bg-background p-4 pt-12">
      <Card className="gap-4 overflow-hidden py-0">
        <video ref={videoRef} tabIndex={0} controls preload="metadata" src={mediaHref(taskId, result.video)} className="aspect-video w-full bg-black object-contain" />
        <CardHeader className="pb-4">
          <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground"><VideoIcon className="size-3.5" />辅助视频</div>
          <CardTitle className="text-base leading-6">{currentSection?.title || "等待播放"}</CardTitle>
          <p className="font-mono text-xs text-muted-foreground">{currentSection ? `${currentSection.start_time}–${currentSection.end_time}` : "点击文章、大纲或转写中的时间位置"}</p>
        </CardHeader>
      </Card>
    </aside>
  )
}

function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) {
    return false
  }
  if (target.isContentEditable) {
    return true
  }
  return ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)
}

function findCurrentSection(sections: OutlineSection[], currentTime: number): OutlineSection | null {
  return sections.find((section) => currentTime >= section.start_sec && currentTime <= section.end_sec) || null
}

function ResultSkeleton() {
  return <div className="space-y-4 p-6"><Skeleton className="h-10 w-2/3" /><Skeleton className="h-[70vh]" /></div>
}
