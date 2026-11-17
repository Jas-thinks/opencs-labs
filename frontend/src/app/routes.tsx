import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "../app/AuthContext";
import { Layout } from "../app/Layout";
import { Loading } from "../components/ui";
import { Login } from "../features/auth/Login";
import { LearnHome } from "../features/learning/LearnHome";
import { LessonPage } from "../features/learning/LessonPage";
import { PracticeHome } from "../features/practice/PracticeHome";
import { ExercisePage } from "../features/practice/ExercisePage";
import { NotebooksHome } from "../features/notebooks/NotebooksHome";
import { DatasetsHome } from "../features/datasets/DatasetsHome";
import { DatasetPage } from "../features/datasets/DatasetPage";
import { DashboardPage } from "../features/grading/DashboardPage";
import { TeachingPage } from "../features/grading/TeachingPage";
import { StudentDetailPage } from "../features/grading/StudentDetailPage";
import { AssignmentPage } from "../features/grading/AssignmentPage";

function Protected({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) return <Loading label="Checking your session…" />;
  if (!user) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

export function AppRoutes() {
  const { user, loading } = useAuth();

  return (
    <Routes>
      <Route
        path="/login"
        element={loading ? <Loading /> : user ? <Navigate to="/learn" replace /> : <Login />}
      />
      <Route
        element={
          <Protected>
            <Layout />
          </Protected>
        }
      >
        <Route path="/learn" element={<LearnHome />} />
        <Route path="/learn/:lessonSlug" element={<LessonPage />} />
        <Route path="/practice" element={<PracticeHome />} />
        <Route path="/practice/:exerciseSlug" element={<ExercisePage />} />
        <Route path="/notebooks" element={<NotebooksHome />} />
        <Route path="/datasets" element={<DatasetsHome />} />
        <Route path="/datasets/:datasetSlug" element={<DatasetPage />} />
        <Route path="/dashboard" element={<DashboardPage />} />
        <Route path="/teaching" element={<TeachingPage />} />
        <Route path="/teaching/courses/:courseId/students/:userId" element={<StudentDetailPage />} />
        <Route path="/assignments/:assignmentId" element={<AssignmentPage />} />
      </Route>
      <Route path="*" element={<Navigate to={user ? "/learn" : "/login"} replace />} />
    </Routes>
  );
}
