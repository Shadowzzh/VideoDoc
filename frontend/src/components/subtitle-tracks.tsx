import { mediaHref } from "@/lib/api"
import type { SubtitleTrack } from "@/types"

interface SubtitleTracksProps {
  taskId: string
  tracks?: SubtitleTrack[]
  /** 默认轨的模式；不在列表里时退回第一条。 */
  mode?: string | null
}

/**
 * 播放器的字幕轨集合：中文与中英可以同时存在，用户在播放器字幕菜单里切换。
 * 只允许一条带 default，否则浏览器行为不确定。
 */
export function SubtitleTracks({ taskId, tracks, mode }: SubtitleTracksProps) {
  if (!tracks || tracks.length === 0) {
    return null
  }
  const active = mode && tracks.some((track) => track.mode === mode) ? mode : tracks[0].mode

  return (
    <>
      {tracks.map((track) => (
        <track
          key={track.mode}
          kind="subtitles"
          srcLang="zh"
          label={track.label}
          src={mediaHref(taskId, track.vtt)}
          default={track.mode === active}
        />
      ))}
    </>
  )
}
