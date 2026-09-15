import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { StatusBadge } from "@/components/status-badge"

describe("StatusBadge", () => {
  it("renders localized status", () => {
    render(<StatusBadge status="running" />)
    expect(screen.getByText("运行中")).toBeInTheDocument()
  })
})
