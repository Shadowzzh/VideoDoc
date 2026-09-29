import type { OutlineSection } from "@/types"

export interface SectionAnchor {
  id: string
  element: HTMLElement
}

export interface SectionAnchorPosition {
  id: string
  top: number
}

function normalizeHeadingText(value: string | null | undefined): string {
  return (value ?? "").replace(/\s+/g, " ").trim()
}

/**
 * 把大纲章节与文章中的 `h2` 标题按顺序对齐。
 *
 * 文章的 `h2` 里混有模型写在正文里的小标题，数量和顺序都不能直接当索引用，
 * 所以这里按章节顺序做「文本精确匹配 + 游标只前进」的贪心匹配：只认与章节
 * 标题逐字相同的 `h2`，并且不允许回头匹配更靠前的标题。
 */
export function matchSectionAnchors(article: HTMLElement, sections: OutlineSection[]): SectionAnchor[] {
  const headings = Array.from(article.querySelectorAll<HTMLElement>("h2"))
  const anchors: SectionAnchor[] = []
  let cursor = 0
  for (const section of sections) {
    const target = normalizeHeadingText(section.title)
    for (let index = cursor; index < headings.length; index += 1) {
      if (normalizeHeadingText(headings[index].textContent) !== target) {
        continue
      }
      anchors.push({ id: section.id, element: headings[index] })
      cursor = index + 1
      break
    }
  }
  return anchors
}

/**
 * 判断文章视口顶部当前落在哪一节。
 *
 * - 滚到底时直接取最后一节，避免底部留白让最后几节永远越不过阅读线。
 * - 正常情况下取最后一个越过阅读线的标题；一个都没越过说明还在文章开头，取第一节。
 */
export function pickActiveSectionId(
  positions: SectionAnchorPosition[],
  options: { viewportTop: number; line: number; atBottom: boolean },
): string | null {
  if (positions.length === 0) {
    return null
  }
  if (options.atBottom) {
    return positions[positions.length - 1].id
  }
  let activeId: string | null = null
  for (const position of positions) {
    if (position.top - options.viewportTop > options.line) {
      break
    }
    activeId = position.id
  }
  return activeId ?? positions[0].id
}
