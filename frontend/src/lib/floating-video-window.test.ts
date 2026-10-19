import { describe, expect, it } from "vitest"

import {
  FLOATING_VIDEO_MARGIN,
  clampFloatingVideoRect,
  decodeFloatingVideoRect,
  defaultFloatingVideoRect,
  floatingVideoHeight,
  floatingVideoWidthLimits,
  maximizedFloatingVideoRect,
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
