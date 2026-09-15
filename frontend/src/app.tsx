import { ErrorState } from "@/components/error-state"
import { HomePage } from "@/pages/home-page"
import { ResultPage } from "@/pages/result-page"
import { TaskPage } from "@/pages/task-page"

type Route =
  | { name: "home" }
  | { name: "task"; taskId: string }
  | { name: "result"; taskId: string }
  | { name: "not-found" }

function currentRoute(): Route {
  const path = window.location.pathname.replace(/^\/app\/?/, "").replace(/\/$/, "")
  if (!path) {
    return { name: "home" }
  }
  const resultMatch = path.match(/^tasks\/([^/]+)\/result$/)
  if (resultMatch) {
    return { name: "result", taskId: decodeURIComponent(resultMatch[1]) }
  }
  const taskMatch = path.match(/^tasks\/([^/]+)$/)
  if (taskMatch) {
    return { name: "task", taskId: decodeURIComponent(taskMatch[1]) }
  }
  return { name: "not-found" }
}

export function App() {
  const route = currentRoute()
  if (route.name === "home") {
    return <HomePage />
  }
  if (route.name === "task") {
    return <TaskPage taskId={route.taskId} />
  }
  if (route.name === "result") {
    return <ResultPage taskId={route.taskId} />
  }
  return <div className="mx-auto max-w-2xl p-8"><ErrorState title="页面不存在" message="请返回 VideoDoc 任务台。" /></div>
}
