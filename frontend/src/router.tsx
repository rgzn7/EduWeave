import { createBrowserRouter, Navigate } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { AssessmentDetailPage } from "./pages/AssessmentDetailPage";
import { AssistantPage } from "./pages/AssistantPage";
import { BatchDetailPage } from "./pages/BatchDetailPage";
import { CoverageReportPage } from "./pages/CoverageReportPage";
import { DashboardPage } from "./pages/DashboardPage";
import { LearnerProfileReportPage } from "./pages/LearnerProfileReportPage";
import { LoginPage } from "./pages/LoginPage";
import { ProjectWorkspacePage } from "./pages/ProjectWorkspacePage";
import { TaskDetailPage } from "./pages/TaskDetailPage";
import { useAuthStore } from "./stores/auth";

function RequireAuth() {
  const token = useAuthStore((state) => state.token);
  if (!token) {
    return <Navigate to="/login" replace />;
  }
  return <AppShell />;
}

export const router = createBrowserRouter([
  {
    path: "/login",
    element: <LoginPage />,
  },
  {
    path: "/",
    element: <RequireAuth />,
    children: [
      {
        index: true,
        element: <DashboardPage />,
      },
      {
        path: "history",
        element: <DashboardPage />,
      },
      {
        path: "assistant",
        element: <AssistantPage />,
      },
      {
        path: "projects/:projectId",
        element: <ProjectWorkspacePage />,
      },
      {
        path: "projects/:projectId/batches/:batchId",
        element: <BatchDetailPage />,
      },
      {
        path: "projects/:projectId/batches/:batchId/assessments/:paperResultId",
        element: <AssessmentDetailPage />,
      },
      {
        path: "projects/:projectId/batches/:batchId/homework/:homeworkResultId",
        element: <AssessmentDetailPage />,
      },
      {
        path: "projects/:projectId/batches/:batchId/learner-profile/:profileVersionId",
        element: <LearnerProfileReportPage />,
      },
      {
        path: "projects/:projectId/learner-profile/:profileVersionId",
        element: <LearnerProfileReportPage />,
      },
      {
        path: "projects/:projectId/batches/:batchId/coverage/:coverageReportId",
        element: <CoverageReportPage />,
      },
      {
        path: "tasks/:taskId",
        element: <TaskDetailPage />,
      },
    ],
  },
]);
