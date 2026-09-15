import { AlertCircleIcon } from "lucide-react"

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"

export function ErrorState({ title = "加载失败", message }: { title?: string; message: string }) {
  return (
    <Card className="border-destructive/30 bg-destructive/5">
      <CardHeader className="pb-0">
        <CardTitle className="flex items-center gap-2 text-base text-destructive"><AlertCircleIcon className="size-4" />{title}</CardTitle>
      </CardHeader>
      <CardContent className="text-sm text-muted-foreground">{message}</CardContent>
    </Card>
  )
}
