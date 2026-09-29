import { describe, expect, it } from "vitest"

import { matchSectionAnchors, pickActiveSectionId } from "@/lib/outline-anchors"
import type { OutlineSection } from "@/types"

function section(id: string, title: string): OutlineSection {
  return {
    id,
    title,
    summary: "",
    start_segment_id: "seg-00001",
    end_segment_id: "seg-00001",
    start_sec: 0,
    end_sec: 1,
    start_time: "00:00",
    end_time: "00:01",
  }
}

// 取自真实任务 20260928-175925-76ef38a1：文章里有 14 个 h2，但大纲只有 10 节，
// 多出来的 4 个是模型写在正文里的小标题。
const sections = [
  section("section-01", "开场：AI时代普通人的困惑与嘉宾介绍"),
  section("section-02", "卡兹克评估AI产品的三个标准"),
  section("section-03", "2023年开公众号的三大预判"),
  section("section-04", "信息洪流与两种信息筛选方式"),
  section("section-05", "信息源与IP信任：诺兰的例子"),
  section("section-06", "实践出真知：从被攻击到搞定网站"),
  section("section-07", "普通人的两个关键品质：勇气与好奇心"),
  section("section-08", "AI与普通人的关系及管理者的挑战"),
  section("section-09", "给自媒体人的建议：注意力是护城河"),
  section("section-10", "结尾花絮"),
]

const articleHtml = [
  "<h1>标题</h1>",
  ...sections.map((item) => `<h2>${item.title}</h2><p>${item.id} 正文</p>`).flatMap((item, index) =>
    index === 7 ? [item, "<h2>狂热与无感并存</h2><p>小标题</p>", "<h2>冲击不在执行层，而在管理层</h2><p>小标题</p>"] : [item],
  ),
  "<h2>总结</h2>",
].join("")

function renderArticle(html: string): HTMLElement {
  const article = document.createElement("article")
  article.innerHTML = html
  return article
}

describe("matchSectionAnchors", () => {
  it("skips model-written sub headings and keeps every section aligned", () => {
    const anchors = matchSectionAnchors(renderArticle(articleHtml), sections)

    expect(anchors.map((anchor) => anchor.id)).toEqual(sections.map((item) => item.id))
    expect(anchors.map((anchor) => anchor.element.textContent)).toEqual(sections.map((item) => item.title))
  })

  it("does not reuse an earlier heading for a later section", () => {
    const repeated = renderArticle(
      [
        "<h2>开场</h2>",
        "<h2>重复的开场</h2>",
        "<h2>重复的开场</h2>",
        "<h2>结尾</h2>",
      ].join(""),
    )
    const anchors = matchSectionAnchors(repeated, [section("section-01", "重复的开场"), section("section-02", "结尾")])

    expect(anchors.map((anchor) => anchor.id)).toEqual(["section-01", "section-02"])
    expect(anchors[0].element.textContent).toBe("重复的开场")
    expect(anchors[1].element.textContent).toBe("结尾")
  })

  it("tolerates whitespace differences and missing sections", () => {
    const anchors = matchSectionAnchors(renderArticle("<h2>  开场\n 章节 </h2>"), [
      section("section-01", "开场 章节"),
      section("section-02", "不存在的章节"),
    ])

    expect(anchors.map((anchor) => anchor.id)).toEqual(["section-01"])
  })
})

describe("pickActiveSectionId", () => {
  const positions = [
    { id: "section-01", top: -400 },
    { id: "section-02", top: 40 },
    { id: "section-03", top: 600 },
  ]

  it("picks the last heading above the reading line", () => {
    expect(pickActiveSectionId(positions, { viewportTop: 0, line: 96, atBottom: false })).toBe("section-02")
  })

  it("falls back to the first section before any heading crosses the line", () => {
    expect(
      pickActiveSectionId(
        [
          { id: "section-01", top: 300 },
          { id: "section-02", top: 900 },
        ],
        { viewportTop: 0, line: 96, atBottom: false },
      ),
    ).toBe("section-01")
  })

  it("pins the last section when scrolled to the bottom", () => {
    expect(pickActiveSectionId(positions, { viewportTop: 0, line: 96, atBottom: true })).toBe("section-03")
  })

  it("returns null without anchors", () => {
    expect(pickActiveSectionId([], { viewportTop: 0, line: 96, atBottom: true })).toBeNull()
  })
})
