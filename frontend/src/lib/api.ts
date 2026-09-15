import type { TaskDeletionPreview, VideoResult, VideoTask } from "@/types"

async function requestJson<T>(input: RequestInfo | URL, init?: RequestInit): Promise<T> {
  const response = await fetch(input, init)
  if (!response.ok) {
    let message = `HTTP ${response.status}`
    try {
      const payload = (await response.json()) as { error?: string }
      if (payload.error) {
        message = payload.error
      }
    } catch {
      message = response.statusText || message
    }
    throw new Error(message)
  }
  return (await response.json()) as T
}

export function listTasks(): Promise<VideoTask[]> {
  return requestJson<VideoTask[]>("/api/tasks", { cache: "no-store" })
}

export function getTask(taskId: string): Promise<VideoTask> {
  return requestJson<VideoTask>(`/api/tasks/${taskId}`, { cache: "no-store" })
}

export function getResult(taskId: string): Promise<VideoResult> {
  return requestJson<VideoResult>(`/api/tasks/${taskId}/result`, { cache: "no-store" })
}

export function createTask(url: string): Promise<{ id: string; url: string }> {
  return requestJson<{ id: string; url: string }>("/api/tasks", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
  })
}

export function resumeTask(taskId: string): Promise<{ id: string; resume_from: string }> {
  return requestJson<{ id: string; resume_from: string }>(`/api/tasks/${taskId}/resume`, {
    method: "POST",
  })
}

export function getTaskDeletionPreview(taskId: string): Promise<TaskDeletionPreview> {
  return requestJson<TaskDeletionPreview>(`/api/tasks/${taskId}/deletion-preview`, {
    cache: "no-store",
  })
}

export function deleteTask(taskId: string): Promise<{ id: string; deleted_at: string; recoverable: boolean }> {
  return requestJson<{ id: string; deleted_at: string; recoverable: boolean }>(`/api/tasks/${taskId}`, {
    method: "DELETE",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ confirmation: taskId }),
  })
}

export function taskHref(taskId: string): string {
  return `/app/tasks/${taskId}`
}

export function resultHref(taskId: string): string {
  return `/app/tasks/${taskId}/result`
}

export function primaryTaskHref(task: VideoTask): string {
  if (task.status === "completed") {
    return resultHref(task.id)
  }
  return taskHref(task.id)
}

export function mediaHref(taskId: string, filename: string): string {
  return `/tasks/${taskId}/media/${filename}`
}

export function downloadHref(taskId: string, filename: string): string {
  return `/tasks/${taskId}/download/${filename}`
}
