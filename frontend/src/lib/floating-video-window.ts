export interface FloatingVideoRect {
  x: number
  y: number
  width: number
  height: number
}

export interface ViewportSize {
  width: number
  height: number
}

export type FloatingVideoMode = "hidden" | "normal" | "maximized" | "fullscreen"
export type MaximizedOrigin = "hidden" | "normal"
export type FullscreenOrigin = "normal" | "maximized"

/**
 * V 键和全屏按钮共享的状态。`maximizedFrom`/`fullscreenFrom` 记住放大前的来源，
 * 这样从小窗进入最大化会回到小窗，从关闭状态进入最大化会直接关闭。
 */
export interface FloatingVideoModeState {
  mode: FloatingVideoMode
  maximizedFrom: MaximizedOrigin
  fullscreenFrom: FullscreenOrigin
}

export const INITIAL_FLOATING_VIDEO_MODE_STATE: FloatingVideoModeState = {
  mode: "normal",
  maximizedFrom: "normal",
  fullscreenFrom: "maximized",
}

export function toggleFloatingVideoSize(state: FloatingVideoModeState): FloatingVideoModeState {
  switch (state.mode) {
    case "hidden":
      return { ...state, mode: "maximized", maximizedFrom: "hidden" }
    case "normal":
      return { ...state, mode: "maximized", maximizedFrom: "normal" }
    case "maximized":
      return { ...state, mode: state.maximizedFrom }
    case "fullscreen":
      // 全屏是最高的放大档，再按 V 收回到进入全屏前的档位。
      return { ...state, mode: state.fullscreenFrom }
  }
}

export function enterFloatingVideoFullscreen(state: FloatingVideoModeState): FloatingVideoModeState {
  if (state.mode === "fullscreen") {
    return state
  }
  return {
    mode: "fullscreen",
    maximizedFrom: state.maximizedFrom,
    // 从关闭状态进入全屏时，退出全屏应停在最大化而不是重新关上。
    fullscreenFrom: state.mode === "normal" ? "normal" : "maximized",
  }
}

export function exitFloatingVideoFullscreen(state: FloatingVideoModeState): FloatingVideoModeState {
  if (state.mode !== "fullscreen") {
    return state
  }
  return { ...state, mode: state.fullscreenFrom }
}

export function hideFloatingVideo(state: FloatingVideoModeState): FloatingVideoModeState {
  return { ...state, mode: "hidden" }
}

export function revealFloatingVideo(state: FloatingVideoModeState): FloatingVideoModeState {
  if (state.mode !== "hidden") {
    return state
  }
  return { ...state, mode: "normal" }
}

export interface PersistedFloatingVideoRect {
  x?: unknown
  y?: unknown
  width?: unknown
  height?: unknown
}

export const FLOATING_VIDEO_ASPECT_RATIO = 16 / 9
export const FLOATING_VIDEO_FOOTER_HEIGHT = 72
export const FLOATING_VIDEO_MARGIN = 16
export const FLOATING_VIDEO_MIN_WIDTH = 320
export const FLOATING_VIDEO_MAX_WIDTH = 1152
export const FLOATING_VIDEO_DEFAULT_WIDTH = 360

export function floatingVideoHeight(width: number): number {
  return width / FLOATING_VIDEO_ASPECT_RATIO + FLOATING_VIDEO_FOOTER_HEIGHT
}

export function floatingVideoWidthLimits(viewport: ViewportSize): { minWidth: number; maxWidth: number } {
  const availableWidth = Math.max(1, viewport.width - FLOATING_VIDEO_MARGIN * 2)
  const availableVideoHeight = Math.max(1, viewport.height - FLOATING_VIDEO_MARGIN * 2 - FLOATING_VIDEO_FOOTER_HEIGHT)
  const widthFromHeight = availableVideoHeight * FLOATING_VIDEO_ASPECT_RATIO
  const maxWidth = Math.max(1, Math.min(FLOATING_VIDEO_MAX_WIDTH, availableWidth, widthFromHeight))
  return {
    minWidth: Math.min(FLOATING_VIDEO_MIN_WIDTH, maxWidth),
    maxWidth,
  }
}

export function clampFloatingVideoRect(rect: FloatingVideoRect, viewport: ViewportSize): FloatingVideoRect {
  const { minWidth, maxWidth } = floatingVideoWidthLimits(viewport)
  const width = clamp(rect.width, minWidth, maxWidth)
  const height = floatingVideoHeight(width)
  const maxX = Math.max(FLOATING_VIDEO_MARGIN, viewport.width - FLOATING_VIDEO_MARGIN - width)
  const maxY = Math.max(FLOATING_VIDEO_MARGIN, viewport.height - FLOATING_VIDEO_MARGIN - height)
  return {
    x: clamp(rect.x, FLOATING_VIDEO_MARGIN, maxX),
    y: clamp(rect.y, FLOATING_VIDEO_MARGIN, maxY),
    width,
    height,
  }
}

export function defaultFloatingVideoRect(viewport: ViewportSize): FloatingVideoRect {
  const { maxWidth } = floatingVideoWidthLimits(viewport)
  const width = Math.min(FLOATING_VIDEO_DEFAULT_WIDTH, maxWidth)
  const height = floatingVideoHeight(width)
  return {
    x: viewport.width - FLOATING_VIDEO_MARGIN - width,
    y: viewport.height - FLOATING_VIDEO_MARGIN - height,
    width,
    height,
  }
}

export function maximizedFloatingVideoRect(viewport: ViewportSize): FloatingVideoRect {
  const { maxWidth } = floatingVideoWidthLimits(viewport)
  const height = floatingVideoHeight(maxWidth)
  return {
    x: (viewport.width - maxWidth) / 2,
    y: (viewport.height - height) / 2,
    width: maxWidth,
    height,
  }
}

export function decodeFloatingVideoRect(value: PersistedFloatingVideoRect): FloatingVideoRect | null {
  const { x, y, width, height } = value
  if (
    typeof x !== "number" || !Number.isFinite(x)
    || typeof y !== "number" || !Number.isFinite(y)
    || typeof width !== "number" || !Number.isFinite(width)
    || typeof height !== "number" || !Number.isFinite(height)
  ) {
    return null
  }
  return { x, y, width, height }
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(Math.max(value, minimum), maximum)
}
