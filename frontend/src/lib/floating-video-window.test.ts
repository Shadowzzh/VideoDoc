import { describe, expect, it } from "vitest"

import {
  FLOATING_VIDEO_MARGIN,
  INITIAL_FLOATING_VIDEO_MODE_STATE,
  clampFloatingVideoRect,
  decodeFloatingVideoRect,
  defaultFloatingVideoRect,
  enterFloatingVideoFullscreen,
  exitFloatingVideoFullscreen,
  floatingVideoHeight,
  floatingVideoWidthLimits,
  hideFloatingVideo,
  maximizedFloatingVideoRect,
  revealFloatingVideo,
  toggleFloatingVideoSize,
} from "@/lib/floating-video-window"

describe("floating video window geometry", () => {
  it("places the default window in the bottom-right corner", () => {
    const rect = defaultFloatingVideoRect({ width: 1024, height: 768 })

    expect(rect.width).toBe(360)
    expect(rect.height).toBe(floatingVideoHeight(360))
    expect(rect.x + rect.width).toBe(1024 - FLOATING_VIDEO_MARGIN)
    expect(rect.y + rect.height).toBe(768 - FLOATING_VIDEO_MARGIN)
  })

  it("limits the maximum width by both viewport width and height", () => {
    expect(floatingVideoWidthLimits({ width: 1920, height: 1080 }).maxWidth).toBe(1152)
    expect(floatingVideoWidthLimits({ width: 1024, height: 600 }).maxWidth).toBeCloseTo(881.78, 2)
  })

  it("clamps persisted position and size back into the visible viewport", () => {
    const rect = clampFloatingVideoRect({
      x: 1800,
      y: -400,
      width: 1400,
      height: 900,
    }, { width: 1280, height: 720 })

    expect(rect.x).toBeGreaterThanOrEqual(FLOATING_VIDEO_MARGIN)
    expect(rect.y).toBe(FLOATING_VIDEO_MARGIN)
    expect(rect.x + rect.width).toBeLessThanOrEqual(1280 - FLOATING_VIDEO_MARGIN)
    expect(rect.y + rect.height).toBeLessThanOrEqual(720 - FLOATING_VIDEO_MARGIN)
    expect(rect.height).toBe(floatingVideoHeight(rect.width))
  })

  it("centers the maximized window while preserving viewport margins", () => {
    const rect = maximizedFloatingVideoRect({ width: 1440, height: 900 })

    expect(rect.x).toBeCloseTo((1440 - rect.width) / 2)
    expect(rect.y).toBeCloseTo((900 - rect.height) / 2)
    expect(rect.x).toBeGreaterThanOrEqual(FLOATING_VIDEO_MARGIN)
    expect(rect.y).toBeGreaterThanOrEqual(FLOATING_VIDEO_MARGIN)
  })

  it("rejects invalid persisted geometry", () => {
    expect(decodeFloatingVideoRect({ x: 1, y: 2, width: 3, height: 4 })).toEqual({ x: 1, y: 2, width: 3, height: 4 })
    expect(decodeFloatingVideoRect({ x: 1, y: 2, width: Number.NaN, height: 4 })).toBeNull()
    expect(decodeFloatingVideoRect({ x: 1, y: 2, width: "3", height: 4 })).toBeNull()
  })
})

describe("floating video size cycle", () => {
  it("cycles a visible window between normal and maximized", () => {
    const maximized = toggleFloatingVideoSize(INITIAL_FLOATING_VIDEO_MODE_STATE)
    expect(maximized).toMatchObject({ mode: "maximized", maximizedFrom: "normal" })

    const restored = toggleFloatingVideoSize(maximized)
    expect(restored.mode).toBe("normal")
  })

  it("opens a hidden window maximized and closes it on the next toggle", () => {
    const hidden = hideFloatingVideo(INITIAL_FLOATING_VIDEO_MODE_STATE)
    expect(hidden.mode).toBe("hidden")

    const opened = toggleFloatingVideoSize(hidden)
    expect(opened).toMatchObject({ mode: "maximized", maximizedFrom: "hidden" })

    expect(toggleFloatingVideoSize(opened).mode).toBe("hidden")
  })

  it("returns a hidden window to normal when playback is revealed", () => {
    const hidden = hideFloatingVideo(INITIAL_FLOATING_VIDEO_MODE_STATE)
    expect(revealFloatingVideo(hidden).mode).toBe("normal")
    expect(revealFloatingVideo(INITIAL_FLOATING_VIDEO_MODE_STATE).mode).toBe("normal")
  })

  it("remembers which mode to return to when leaving fullscreen", () => {
    const fromNormal = enterFloatingVideoFullscreen(INITIAL_FLOATING_VIDEO_MODE_STATE)
    expect(fromNormal).toMatchObject({ mode: "fullscreen", fullscreenFrom: "normal" })
    expect(exitFloatingVideoFullscreen(fromNormal).mode).toBe("normal")

    const maximized = toggleFloatingVideoSize(INITIAL_FLOATING_VIDEO_MODE_STATE)
    const fromMaximized = enterFloatingVideoFullscreen(maximized)
    expect(fromMaximized.fullscreenFrom).toBe("maximized")
    expect(exitFloatingVideoFullscreen(fromMaximized).mode).toBe("maximized")
  })

  it("enters fullscreen from hidden without losing the hidden origin", () => {
    const hidden = hideFloatingVideo(INITIAL_FLOATING_VIDEO_MODE_STATE)
    const fullscreen = enterFloatingVideoFullscreen(hidden)

    expect(fullscreen).toMatchObject({ mode: "fullscreen", fullscreenFrom: "maximized", maximizedFrom: "normal" })
    expect(exitFloatingVideoFullscreen(fullscreen).mode).toBe("maximized")
    expect(toggleFloatingVideoSize(fullscreen).mode).toBe("maximized")
  })

  it("ignores redundant fullscreen transitions", () => {
    const fullscreen = enterFloatingVideoFullscreen(INITIAL_FLOATING_VIDEO_MODE_STATE)
    expect(enterFloatingVideoFullscreen(fullscreen)).toBe(fullscreen)
    expect(exitFloatingVideoFullscreen(INITIAL_FLOATING_VIDEO_MODE_STATE).mode).toBe("normal")
  })
})
