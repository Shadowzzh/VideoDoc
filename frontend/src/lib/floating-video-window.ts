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
