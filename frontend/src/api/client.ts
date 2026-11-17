import type {
  AssignmentListResponse,
  AssignmentOut,
  AttemptCreateResponse,
  AttemptOut,
  CategorySummary,
  CourseListResponse,
  CourseOut,
  DatasetDetail,
  DatasetListResponse,
  DatasetVersionOut,
  ExerciseDetail,
  ExerciseListResponse,
  FeedbackResponse,
  GradeListResponse,
  GradeOut,
  LaunchResponse,
  LessonDetail,
  LessonProgressOut,
  MyGradesResponse,
  OpenNotebookResponse,
  PathsResponse,
  PracticeProgress,
  Preferences,
  PreviewResponse,
  RosterResponse,
  RubricOut,
  ServerStateOut,
  SnippetResponse,
  StudentDashboard,
  StudentDrilldown,
  SubmissionListResponse,
  SubmissionOut,
  TeacherDashboard,
  TopicSummary,
  UserOut,
} from "./types";

export const API_BASE =
  (import.meta.env.VITE_API_BASE as string | undefined) ?? "/api/v1";

export class ApiError extends Error {
  code: string;
  status: number;
  details: Record<string, unknown>;

  constructor(status: number, code: string, message: string, details: Record<string, unknown> = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

let unauthorizedHandler: (() => void) | null = null;

export function onUnauthorized(handler: () => void): void {
  unauthorizedHandler = handler;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    credentials: "include",
    headers: {
      Accept: "application/json",
      ...(init.body ? { "Content-Type": "application/json" } : {}),
      ...(init.headers ?? {}),
    },
    ...init,
  });

  if (response.status === 204) {
    return undefined as T;
  }

  const text = await response.text();
  let payload: unknown = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = null;
    }
  }

  if (!response.ok) {
    const error = (payload as { error?: { code?: string; message?: string; details?: Record<string, unknown> } } | null)?.error;
    if (response.status === 401 && unauthorizedHandler) {
      unauthorizedHandler();
    }
    throw new ApiError(
      response.status,
      error?.code ?? "HTTP_ERROR",
      error?.message ?? `Request failed with status ${response.status}`,
      error?.details ?? {},
    );
  }

  return payload as T;
}

function query(params: Record<string, string | number | boolean | undefined | null>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue;
    search.set(key, String(value));
  }
  const encoded = search.toString();
  return encoded ? `?${encoded}` : "";
}

export const api = {
  // auth
  login: (email: string, password: string) =>
    request<{ user: UserOut; expires_in: number }>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),
  logout: () => request<{ ok: boolean }>("/auth/logout", { method: "POST" }),
  authMode: () => request<{ mode: string }>("/auth/mode"),

  // profile
  me: () => request<UserOut>("/me"),
  getPreferences: () => request<Preferences>("/me/preferences"),
  updatePreferences: (payload: Preferences) =>
    request<Preferences>("/me/preferences", { method: "PATCH", body: JSON.stringify(payload) }),
  myCourses: () => request<unknown>("/me/courses"),

  // learning
  paths: () => request<PathsResponse>("/learning/paths"),
  modules: () => request<{ modules: unknown[] }>("/learning/modules"),
  lesson: (slug: string) => request<LessonDetail>(`/learning/lessons/${encodeURIComponent(slug)}`),
  updateProgress: (slug: string, status: string, lastSection?: string) =>
    request<LessonProgressOut>(`/learning/lessons/${encodeURIComponent(slug)}/progress`, {
      method: "POST",
      body: JSON.stringify({ status, last_section: lastSection ?? null }),
    }),
  launchLesson: (slug: string) =>
    request<LaunchResponse>(`/learning/lessons/${encodeURIComponent(slug)}/launch`, {
      method: "POST",
    }),

  // practice
  exercises: (params: {
    topic?: string;
    difficulty?: string;
    q?: string;
    limit?: number;
    offset?: number;
  } = {}) => request<ExerciseListResponse>(`/practice/exercises${query(params)}`),
  exerciseTopics: () => request<TopicSummary[]>("/practice/topics"),
  practiceProgress: () => request<PracticeProgress>("/practice/progress"),
  exercise: (slug: string) =>
    request<ExerciseDetail>(`/practice/exercises/${encodeURIComponent(slug)}`),
  createAttempt: (slug: string) =>
    request<AttemptCreateResponse>(`/practice/exercises/${encodeURIComponent(slug)}/attempts`, {
      method: "POST",
    }),
  attempt: (attemptId: string) =>
    request<AttemptOut>(`/practice/attempts/${encodeURIComponent(attemptId)}`),
  evaluateAttempt: (attemptId: string) =>
    request<FeedbackResponse>(`/practice/attempts/${encodeURIComponent(attemptId)}/evaluate`, {
      method: "POST",
    }),
  attemptFeedback: (attemptId: string) =>
    request<FeedbackResponse>(`/practice/attempts/${encodeURIComponent(attemptId)}/feedback`),

  // datasets
  datasets: (params: {
    q?: string;
    category?: string;
    tag?: string;
    limit?: number;
    offset?: number;
  } = {}) => request<DatasetListResponse>(`/datasets${query(params)}`),
  datasetCategories: () => request<CategorySummary[]>("/datasets/categories"),
  dataset: (slug: string) => request<DatasetDetail>(`/datasets/${encodeURIComponent(slug)}`),
  datasetPreview: (slug: string, limit = 20) =>
    request<PreviewResponse>(`/datasets/${encodeURIComponent(slug)}/preview${query({ limit })}`),
  datasetSnippet: (slug: string, version?: number) =>
    request<SnippetResponse>(
      `/datasets/${encodeURIComponent(slug)}/snippet${query({ version })}`,
    ),
  datasetVersions: (slug: string) =>
    request<DatasetVersionOut[]>(`/datasets/${encodeURIComponent(slug)}/versions`),

  // notebooks
  serverState: () => request<ServerStateOut>("/notebooks/server"),
  startServer: () => request<ServerStateOut>("/notebooks/server/start", { method: "POST" }),
  stopServer: () => request<ServerStateOut>("/notebooks/server/stop", { method: "POST" }),
  notebooks: () => request<{ notebooks: import("./types").NotebookOut[]; total: number }>("/notebooks"),
  createNotebook: (title: string) =>
    request<import("./types").NotebookOut>("/notebooks", {
      method: "POST",
      body: JSON.stringify({ title }),
    }),
  renameNotebook: (id: string, title: string) =>
    request<import("./types").NotebookOut>(`/notebooks/${encodeURIComponent(id)}`, {
      method: "PATCH",
      body: JSON.stringify({ title }),
    }),
  deleteNotebook: (id: string) =>
    request<void>(`/notebooks/${encodeURIComponent(id)}`, { method: "DELETE" }),
  openNotebook: (id: string) =>
    request<OpenNotebookResponse>(`/notebooks/${encodeURIComponent(id)}/open`),
  downloadNotebookUrl: (id: string) => `${API_BASE}/notebooks/${encodeURIComponent(id)}/download`,

  // courses
  courses: () => request<CourseListResponse>("/courses"),
  course: (id: string) => request<CourseOut>(`/courses/${encodeURIComponent(id)}`),
  roster: (id: string, params: { limit?: number; offset?: number } = {}) =>
    request<RosterResponse>(`/courses/${encodeURIComponent(id)}/roster${query(params)}`),

  // assignments and rubrics
  assignments: (courseId: string) =>
    request<AssignmentListResponse>(
      `/courses/${encodeURIComponent(courseId)}/assignments`,
    ),
  assignment: (id: string) =>
    request<AssignmentOut>(`/assignments/${encodeURIComponent(id)}`),
  createAssignment: (courseId: string, payload: Record<string, unknown>) =>
    request<AssignmentOut>(`/courses/${encodeURIComponent(courseId)}/assignments`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  updateAssignment: (id: string, payload: Record<string, unknown>) =>
    request<AssignmentOut>(`/assignments/${encodeURIComponent(id)}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  rubric: (assignmentId: string) =>
    request<RubricOut>(`/assignments/${encodeURIComponent(assignmentId)}/rubric`),
  upsertRubric: (assignmentId: string, payload: Record<string, unknown>) =>
    request<RubricOut>(`/assignments/${encodeURIComponent(assignmentId)}/rubric`, {
      method: "PUT",
      body: JSON.stringify(payload),
    }),

  // submissions and grading
  submitAssignment: (assignmentId: string, notebookId: string) =>
    request<SubmissionOut>(
      `/assignments/${encodeURIComponent(assignmentId)}/submissions`,
      { method: "POST", body: JSON.stringify({ notebook_id: notebookId }) },
    ),
  submissions: (
    assignmentId: string,
    params: { status?: string; late?: boolean; cursor?: string; limit?: number } = {},
  ) =>
    request<SubmissionListResponse>(
      `/assignments/${encodeURIComponent(assignmentId)}/submissions${query(params)}`,
    ),
  submission: (id: string) =>
    request<SubmissionOut>(`/submissions/${encodeURIComponent(id)}`),
  submissionNotebook: (id: string) =>
    request<Record<string, unknown>>(`/submissions/${encodeURIComponent(id)}/notebook`),
  gradeSubmission: (id: string, payload: Record<string, unknown>) =>
    request<GradeOut>(`/submissions/${encodeURIComponent(id)}/grade`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  submissionGrades: (id: string) =>
    request<GradeListResponse>(`/submissions/${encodeURIComponent(id)}/grades`),
  myGrades: (courseId?: string) =>
    request<MyGradesResponse>(`/me/grades${query({ course_id: courseId })}`),

  // analytics
  myDashboard: (courseId?: string) =>
    request<StudentDashboard>(`/analytics/me${query({ course_id: courseId })}`),
  courseDashboard: (
    courseId: string,
    params: { assignment_id?: string; from?: string; to?: string; limit?: number; offset?: number } = {},
  ) =>
    request<TeacherDashboard>(
      `/analytics/courses/${encodeURIComponent(courseId)}${query(params)}`,
    ),
  studentDrilldown: (courseId: string, userId: string) =>
    request<StudentDrilldown>(
      `/analytics/courses/${encodeURIComponent(courseId)}/students/${encodeURIComponent(userId)}`,
    ),
  courseExportUrl: (courseId: string) =>
    `${API_BASE}/analytics/courses/${encodeURIComponent(courseId)}/export.csv`,
};
