export type TaskStatus = "queued" | "running" | "completed" | "failed" | "cancelled" | "interrupted"
export type StepStatus = "pending" | "running" | "completed" | "failed" | "skipped" | "interrupted"

export interface TaskMetadata {
  id?: string
  title?: string
  description?: string
  uploader?: string
  duration?: number
  webpage_url?: string
  extractor?: string
  thumbnail?: string
}

export interface TaskProgress {
  completed: number
  total: number
  percent: number
}

export interface TaskStep {
  key: string
  label: string
  status: StepStatus
  started_at: string | null
  finished_at: string | null
  command: string | null
  outputs: string[]
  error: string | null
  attempt_count: number
  attempts: TaskAttempt[]
  log_tail?: string
}

export interface TaskAttempt {
  number: number
  status: StepStatus
  started_at: string | null
  finished_at: string | null
  error: string | null
  log: string
}

export interface ResumeStep {
  key: string
  label: string
}

export interface DeletionGroup {
  label: string
  bytes: number
  files: number
}

export interface TaskDeletionPreview {
  id: string
  title: string
  status: TaskStatus
  deletable: boolean
  total_bytes: number
  total_files: number
  groups: Record<string, DeletionGroup>
}

export interface VideoTask {
  id: string
  url: string
  status: TaskStatus
  created_at: string
  updated_at: string
  started_at: string | null
  finished_at: string | null
  error: string | null
  metadata: TaskMetadata
  article_title?: string | null
  artifacts: Record<string, string>
  resume_count: number
  can_resume: boolean
  resume_from: ResumeStep | null
  steps: TaskStep[]
  progress: TaskProgress
}

export interface TranscriptSegment {
  id: string
  start_sec: number
  end_sec: number
  text: string
}

export interface OutlineSection {
  id: string
  title: string
  summary: string
  start_segment_id: string
  end_segment_id: string
  start_sec: number
  end_sec: number
  start_time: string
  end_time: string
}

export interface VideoOutline {
  title: string
  summary: string
  sections: OutlineSection[]
}

export interface ArticleImage {
  section_id: string
  section_title: string
  file: string
  timestamp_sec: number
  timestamp: string
  selection_reason: string
  ocr_text?: string
  ocr_error?: string
  vision_text?: string
  vision_error?: string
  vision_provider?: string
  vision_model?: string
  vision_elapsed_ms?: number
}

export interface VideoResult {
  metadata: TaskMetadata
  article_title?: string
  video: string
  segments: TranscriptSegment[]
  outline: VideoOutline
  images: ArticleImage[]
  article_markdown: string
  article_html: string
}

export type SettingsValue = string | number | boolean | Record<string, string>

export interface SettingsFieldOption {
  value: string
  label: string
}

export type SettingsFieldType = "text" | "password" | "number" | "select" | "boolean" | "textarea"

/** 单个设置项声明：前端按 type 通用渲染，不在前端写死任何能力字段。 */
export interface SettingsField {
  key: string
  label: string
  type: SettingsFieldType
  help: string
  placeholder: string
  options: SettingsFieldOption[]
  minimum: number | null
  maximum: number | null
  secret: boolean
  show_when: { key: string; value: string } | null
}

export interface SettingsGroup {
  title: string
  description: string
  fields: SettingsField[]
}

/** 左侧分类：对应一个可插拔能力（当前只有「图像识别」）。 */
export interface SettingsCategory {
  key: string
  label: string
  description: string
  available: boolean
  unavailable_reason: string
  groups: SettingsGroup[]
}

export interface SettingsResponse {
  /** 当前生效值：capabilities.<能力 key>.<点分字段 key> */
  capabilities: Record<string, Record<string, SettingsValue>>
  /** 左侧分类 + 右侧字段的声明式 schema */
  categories: SettingsCategory[]
  settings_path: string
}

export interface SettingsUpdate {
  capabilities?: Record<string, Record<string, SettingsValue>>
}

export interface SettingsChannelResult {
  ok: boolean
  detail: string
  endpoint?: string
  model_present?: boolean | null
}

export interface SettingsCapabilityResult {
  label?: string
  available?: boolean
  ok?: boolean
  engine?: string
  detail?: string
  local?: SettingsChannelResult
  external?: SettingsChannelResult
}

export interface SettingsTestResult extends SettingsCapabilityResult {
  capabilities?: Record<string, SettingsCapabilityResult>
}
