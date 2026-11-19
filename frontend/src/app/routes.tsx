import { Navigate, Route, Routes, useParams } from "react-router-dom";
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
import { StudentDetailPage } from "../features/grading/StudentDetailPage";
import { GradingWorkspace } from "../features/grading/GradingWorkspace";
import { ToGradePage } from "../features/grading/ToGradePage";
import { StudentHome } from "../features/home/StudentHome";
import { ClassesPage } from "../features/classes/ClassesPage";
import { CourseShell, StaffOnly } from "../features/classes/CourseShell";
import { StreamTab } from "../features/classes/StreamTab";
import { ClassworkTab } from "../features/classes/ClassworkTab";
import { AssignmentDetail } from "../features/classes/AssignmentDetail";
import { AssignmentEditor } from "../features/classes/AssignmentEditor";
import { PeopleTab } from "../features/classes/PeopleTab";
import { GradesTab, InsightsTab } from "../features/classes/GradesTab";

function Protected({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) return <Loading label="Checking your session…" />;
  if (!user) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

/** Pages that only make sense in one experience. UX only: the API enforces access. */
function TeacherOnly({ children }: { children: React.ReactNode }) {
  const { isTeacher } = useAuth();
  return isTeacher ? <>{children}</> : <Navigate to="/home" replace />;
}

export function useLanding(): string {
  const { mode } = useAuth();
  return mode === "teach" ? "/classes" : "/home";
}

function Landing() {
  return <Navigate to={useLanding()} replace />;
}

function LegacyAssignment() {
  const { assignmentId = "" } = useParams();
  return <Navigate to={`/grade/${assignmentId}`} replace />;
}

export function AppRoutes() {
  const { user, loading } = useAuth();

  return (
    <Routes>
      <Route path="/login" element={loading ? <Loading /> : user ? <Landing /> : <Login />} />
      <Route
        element={
          <Protected>
            <Layout />
          </Protected>
        }
      >
        {/* student */}
        <Route path="/home" element={<StudentHome />} />
        <Route path="/progress" element={<DashboardPage />} />

        {/* shared library */}
        <Route path="/learn" element={<LearnHome />} />
        <Route path="/learn/:lessonSlug" element={<LessonPage />} />
        <Route path="/practice" element={<PracticeHome />} />
        <Route path="/practice/:exerciseSlug" element={<ExercisePage />} />
        <Route path="/notebooks" element={<NotebooksHome />} />
        <Route path="/datasets" element={<DatasetsHome />} />
        <Route path="/datasets/:datasetSlug" element={<DatasetPage />} />

        {/* classes: tabs chosen by the viewer's role in each class */}
        <Route path="/classes" element={<ClassesPage />} />
        <Route path="/classes/:courseId" element={<CourseShell />}>
          <Route index element={<Navigate to="stream" replace />} />
          <Route path="stream" element={<StreamTab />} />
          <Route path="classwork" element={<ClassworkTab />} />
          <Route path="classwork/new" element={<StaffOnly><AssignmentEditor /></StaffOnly>} />
          <Route path="classwork/:assignmentId" element={<AssignmentDetail />} />
          <Route path="classwork/:assignmentId/edit" element={<StaffOnly><AssignmentEditor /></StaffOnly>} />
          <Route path="people" element={<StaffOnly><PeopleTab /></StaffOnly>} />
          <Route path="grades" element={<GradesTab />} />
          <Route path="insights" element={<StaffOnly><InsightsTab /></StaffOnly>} />
        </Route>

        {/* teacher */}
        <Route path="/to-grade" element={<TeacherOnly><ToGradePage /></TeacherOnly>} />
        <Route path="/grade/:assignmentId" element={<TeacherOnly><GradingWorkspace /></TeacherOnly>} />
        <Route
          path="/teaching/courses/:courseId/students/:userId"
          element={<TeacherOnly><StudentDetailPage /></TeacherOnly>}
        />

        {/* old links (bookmarks, notifications) */}
        <Route path="/dashboard" element={<Landing />} />
        <Route path="/teaching" element={<Navigate to="/classes" replace />} />
        <Route path="/assignments/:assignmentId" element={<LegacyAssignment />} />
      </Route>
      <Route path="*" element={user ? <Landing /> : <Navigate to="/login" replace />} />
    </Routes>
  );
}
