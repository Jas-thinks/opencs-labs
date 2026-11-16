import type {
  AttemptCreateResponse,
  AttemptOut,
  CategorySummary,
  DatasetDetail,
  DatasetListResponse,
  DatasetVersionOut,
  ExerciseDetail,
  ExerciseListResponse,
  FeedbackResponse,
  LaunchResponse,
  LessonDetail,
  LessonProgressOut,
  OpenNotebookResponse,
  PathsResponse,
  PracticeProgress,
  Preferences,
  PreviewResponse,
  ServerStateOut,
  SnippetResponse,
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

function query(params: Record<string, string | number | undefined | null>): string {
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
};
