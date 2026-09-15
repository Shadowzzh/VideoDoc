import { MoreHorizontalIcon, Trash2Icon } from "lucide-react"
import { useState } from "react"

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogMedia,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { deleteTask, getTaskDeletionPreview } from "@/lib/api"
import { formatBytes, taskTitle } from "@/lib/format"
import type { TaskDeletionPreview, VideoTask } from "@/types"

interface TaskActionsMenuProps {
  task: VideoTask
  onDeleted: () => void
}

export function TaskActionsMenu({ task, onDeleted }: TaskActionsMenuProps) {
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [preview, setPreview] = useState<TaskDeletionPreview | null>(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const deletable = task.status !== "queued" && task.status !== "running"

  const openDeleteDialog = async () => {
    setDeleteOpen(true)
    setPreview(null)
    setError(null)
    setPreviewLoading(true)
    try {
      const value = await getTaskDeletionPreview(task.id)
      setPreview(value)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "无法读取删除范围")
    } finally {
      setPreviewLoading(false)
    }
  }

  const handleDelete = async () => {
    setDeleting(true)
    setError(null)
    try {
      await deleteTask(task.id)
      setDeleteOpen(false)
      onDeleted()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "删除任务失败")
    } finally {
      setDeleting(false)
    }
  }

  let deleteLabel = "删除任务"
  if (!deletable) {
    deleteLabel = "运行中不可删除"
  }

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger
          render={
            <Button
              type="button"
              variant="ghost"
              size="icon"
              aria-label={`${taskTitle(task)}的操作菜单`}
            />
          }
        >
          <MoreHorizontalIcon />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-40">
          <DropdownMenuItem
            variant="destructive"
            disabled={!deletable}
            onClick={() => void openDeleteDialog()}
          >
            <Trash2Icon />
            {deleteLabel}
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      <AlertDialog open={deleteOpen} onOpenChange={setDeleteOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogMedia className="bg-destructive/10 text-destructive">
              <Trash2Icon />
            </AlertDialogMedia>
            <AlertDialogTitle>删除这个任务？</AlertDialogTitle>
            <AlertDialogDescription>
              “{taskTitle(task)}”将从任务列表移除，其视频、音频、转写、关键帧、文章和日志会一起移入 VideoDoc 回收站。
            </AlertDialogDescription>
          </AlertDialogHeader>

          <div className="space-y-3 rounded-lg border bg-muted/30 p-3">
            <p className="break-all font-mono text-[11px] text-muted-foreground">{task.id}</p>
            {previewLoading ? <p className="text-xs text-muted-foreground">正在计算删除范围…</p> : null}
            {preview ? (
              <>
                <div className="flex items-center justify-between text-sm">
                  <span>总占用</span>
                  <strong>{formatBytes(preview.total_bytes)}</strong>
                </div>
                <div className="space-y-1 text-xs text-muted-foreground">
                  {Object.entries(preview.groups).map(([key, group]) => (
                    <div key={key} className="flex items-center justify-between gap-4">
                      <span>{group.label}</span>
                      <span>{group.files} 个文件 · {formatBytes(group.bytes)}</span>
                    </div>
                  ))}
                </div>
              </>
            ) : null}
            {error ? <p className="text-xs text-destructive">{error}</p> : null}
          </div>

          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleting}>取消</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              disabled={previewLoading || preview === null || deleting}
              onClick={() => void handleDelete()}
            >
              {deleting ? "正在删除…" : "移入回收站"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}
