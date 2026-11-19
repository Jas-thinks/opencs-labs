export type Role = "student" | "instructor" | "admin";

export interface Preferences {
  theme?: string;
  editor_font_size?: number;
  default_notebook_profile?: string;
}

export interface TeachingSummary {
  is_teacher: boolean;
  staff_course_count: number;
  student_course_count: number;
  can_create_courses: boolean;
}

export interface UserOut {
  id: string;
  email: string;
  display_name: string;
  role: Role;
  hub_username: string;
  preferences: Preferences;
  teaching?: TeachingSummary;
}

export interface LessonProgressOut {
  status: string;
  last_section: string | null;
  completed_at: string | null;
}

export interface LessonSummary {
  slug: string;
  title: string;
  summary: string;
  objective: string;
  estimated_minutes: number;
  position: number;
  status: string;
  dataset_slugs: string[];
  exercise_slugs: string[];
  has_notebook_activity: boolean;
}

export interface ModuleSummary {
  slug: string;
  title: string;
  description: string;
  position: number;
  lessons: LessonSummary[];
  total_lessons: number;
  completed_lessons: number;
}

export interface PathSummary {
  slug: string;
  title: string;
  description: string;
  modules: ModuleSummary[];
  total_lessons: number;
  completed_lessons: number;
  progress_percent: number;
}

export interface PathsResponse {
  paths: PathSummary[];
  total_lessons: number;
  completed_lessons: number;
}

export interface DatasetRef {
  slug: string;
  title: string;
  summary: string;
  category: string;
  format: string | null;
  row_count: number | null;
}

export interface ExerciseRef {
  slug: string;
  title: string;
  topic: string;
  difficulty: string;
}

export type Block =
  | { type: "markdown"; text: string }
  | { type: "callout"; variant: "info" | "warning" | "tip" | "danger"; title?: string; text: string }
  | { type: "code"; language?: string; caption?: string; source: string }
  | {
      type: "output";
      kind: "text" | "table";
      text?: string;
      columns?: { key: string; label: string }[];
      rows?: Record<string, unknown>[];
    }
  | {
      type: "table";
      caption?: string;
      columns: { key: string; label: string }[];
      rows: Record<string, unknown>[];
    }
  | {
      type: "chart";
      title: string;
      caption?: string;
      spec: {
        type: "scatter" | "bar" | "line";
        x: string;
        y: string;
        series?: string;
        data: Record<string, unknown>[];
      };
    }
  | { type: "steps"; items: { title: string; text: string }[] }
  | { type: "mistakes"; items: { error: string; explanation: string; fix: string }[] }
  | { type: "checklist"; items: string[] }
  | { type: "glossary"; items: { term: string; definition: string }[] };

export interface ContentStage {
  key: string;
  label: string;
  blocks: Block[];
}

export interface LessonContent {
  stages?: ContentStage[];
  takeaways?: string[];
  glossary?: { term: string; definition: string }[];
}

export interface LessonDetail {
  slug: string;
  title: string;
  objective: string;
  summary: string;
  estimated_minutes: number;
  content: LessonContent;
  progress: LessonProgressOut;
  datasets: DatasetRef[];
  exercises: ExerciseRef[];
  module: { slug: string; title: string };
  path: { slug: string; title: string };
  navigation: { previous: string | null; next: string | null };
  has_notebook_activity: boolean;
  version: number;
}

export interface DatasetSummary {
  id: string;
  slug: string;
  title: string;
  summary: string;
  category: string;
  teaching_tags: string[];
  version: number | null;
  format: string | null;
  row_count: number | null;
  size_bytes: number | null;
  license: string | null;
  license_status: string | null;
}

export interface DatasetListResponse {
  datasets: DatasetSummary[];
  total: number;
  limit: number;
  offset: number;
}

export interface DatasetVersionOut {
  version: number;
  format: string;
  size_bytes: number;
  sha256: string;
  row_count: number;
  license: string;
  license_url: string;
  license_status: string;
  source_url: string;
  attribution: string;
  published_at: string | null;
  is_current: boolean;
}

export interface DatasetDetail extends DatasetSummary {
  description: string;
  attribution: string;
  source_url: string;
  license_url: string;
  columns: { name: string; dtype: string }[];
  preview: Record<string, unknown>[];
  versions: DatasetVersionOut[];
  read_only: boolean;
  notes: string;
}

export interface PreviewResponse {
  dataset_id: string;
  version: number;
  format: string;
  row_count: number;
  columns: { name: string; dtype: string }[];
  rows: Record<string, unknown>[];
  truncated: boolean;
  license: string;
  license_status: string;
}

export interface SnippetResponse {
  dataset_id: string;
  version: number;
  language: string;
  cell_type: string;
  auto_execute: boolean;
  code: string;
  path: string;
  read_only: boolean;
}

export interface CategorySummary {
  category: string;
  count: number;
}

export interface ExerciseSummary {
  id: string;
  slug: string;
  title: string;
  topic: string;
  difficulty: string;
  objective: string;
  estimated_minutes: number;
  dataset_slugs: string[];
  has_automated_checks: boolean;
  completed: boolean;
  attempts: number;
}

export interface ExerciseListResponse {
  exercises: ExerciseSummary[];
  total: number;
  limit: number;
  offset: number;
}

export interface HintOut {
  index: number;
  text: string;
}

export interface ExerciseDetail {
  id: string;
  slug: string;
  title: string;
  topic: string;
  difficulty: string;
  objective: string;
  instructions: { markdown?: string };
  hints: HintOut[];
  dataset_slugs: string[];
  datasets: DatasetRef[];
  has_automated_checks: boolean;
  related_lesson_slug: string | null;
  estimated_minutes: number;
  completed: boolean;
  attempts: number;
}

export interface NotebookOut {
  id: string;
  title: string;
  file_name: string;
  kind: string;
  source_ref: string | null;
  environment_image: string;
  size_bytes: number;
  created_at: string;
  updated_at: string;
  last_opened_at: string | null;
}

export interface ServerStateOut {
  running: boolean;
  ready: boolean;
  status: string;
  pending: string | null;
  url?: string | null;
}

export interface AttemptOut {
  id: string;
  exercise_id: string;
  exercise_slug: string;
  attempt_number: number;
  status: string;
  score: number | null;
  started_at: string;
  submitted_at: string | null;
  completed_at: string | null;
  feedback: Record<string, unknown>;
  notebook: NotebookOut | null;
}

export interface AttemptCreateResponse {
  attempt: AttemptOut;
  notebook: NotebookOut;
  url: string;
  hints: HintOut[];
}

export interface FeedbackTest {
  id: string;
  description: string;
  passed: boolean;
  message?: string;
}

export interface FeedbackResponse {
  attempt_id: string;
  status: string;
  passed: boolean;
  score: number | null;
  tests: FeedbackTest[];
  message: string | null;
  evaluated_at: string | null;
}

export interface LaunchResponse {
  notebook: NotebookOut;
  url: string;
  created: boolean;
}

export interface OpenNotebookResponse {
  notebook: NotebookOut;
  url: string;
}

export interface TopicSummary {
  topic: string;
  count: number;
}

export interface PracticeProgress {
  topics: { topic: string; attempts: number; completed: number; exercises: number }[];
  total_exercises: number;
  completed_exercises: number;
}

/* ---- courses, grading and analytics --------------------------------- */

export type CourseRole = "student" | "ta" | "instructor" | "admin" | "staff";

export interface CourseOut {
  id: string;
  name: string;
  code: string;
  term: string;
  status: string;
  description: string;
  role_in_course: CourseRole;
  join_code?: string | null;
}

export interface CourseListResponse {
  courses: CourseOut[];
}

export interface RosterRow {
  user_id: string;
  display_name: string;
  email: string;
  role_in_course: string;
  assigned: number;
  submitted: number;
  completed: number;
  average_score: number | null;
  late_count: number;
  ungraded_count: number;
  last_active_at: string | null;
}

export interface RosterResponse {
  course_id: string;
  rows: RosterRow[];
  total: number;
  limit: number;
  offset: number;
}

export interface AssignmentOut {
  id: string;
  course_id: string;
  exercise_id: string | null;
  exercise_slug: string | null;
  slug: string;
  kind: string;
  title: string;
  description: string;
  due_at: string | null;
  max_points: number;
  weight: number;
  allow_late: boolean;
  late_penalty_pct: number;
  is_published: boolean;
  topic: string | null;
  publish_at: string | null;
  archived_at: string | null;
  is_visible: boolean;
  has_starter: boolean;
  created_by: string;
  created_at: string;
  updated_at: string;
  submission_count: number | null;
  my_submission: MySubmissionRef | null;
}

export interface MySubmissionRef {
  id: string;
  attempt_number: number;
  status: string;
  is_late: boolean;
  final_score: number | null;
  submitted_at: string;
}

export interface AssignmentInput {
  title?: string;
  description?: string;
  kind?: "practice" | "project" | "exam";
  topic?: string | null;
  due_at?: string | null;
  publish_at?: string | null;
  max_points?: number;
  weight?: number;
  allow_late?: boolean;
  late_penalty_pct?: number;
  is_published?: boolean;
  exercise_slug?: string | null;
  starter_notebook_id?: string | null;
  clear_starter?: boolean;
}

export interface AssignmentListResponse {
  assignments: AssignmentOut[];
}

export interface RubricCriterionOut {
  id: string;
  key: string;
  label: string;
  description: string;
  max_points: number;
  position: number;
}

export interface RubricOut {
  id: string;
  assignment_id: string;
  title: string;
  total_points: number;
  criteria: RubricCriterionOut[];
}

export interface SubmissionOut {
  id: string;
  assignment_id: string;
  user_id: string;
  student: { id: string; display_name: string } | null;
  notebook_id: string;
  attempt_number: number;
  status: string;
  is_late: boolean;
  auto_score: number | null;
  final_score: number | null;
  score_source: string;
  submitted_at: string;
  graded_at: string | null;
  notebook_version: { version_number: number; sha256: string } | null;
  has_draft?: boolean;
}

export interface SubmissionListResponse {
  submissions: SubmissionOut[];
  next_cursor: string | null;
}

export interface GradeCriterionOut {
  criterion_id: string;
  key: string;
  label: string;
  max_points: number;
  points: number;
  comment: string;
}

export interface GradeOut {
  id: string;
  submission_id: string;
  revision: number;
  rubric_id: string;
  total_points: number;
  final_score: number | null;
  override_reason?: string | null;
  feedback: string;
  graded_by: string;
  published_at: string;
  released_at?: string | null;
  state?: "draft" | "released";
  criteria: GradeCriterionOut[];
}

export interface GradeInput {
  criteria: { criterion_id: string; points: number; comment?: string }[];
  feedback?: string;
  final_score?: number | null;
  override_reason?: string | null;
  release?: boolean;
}

export interface SubmissionDetailOut extends SubmissionOut {
  latest_grade: GradeOut | null;
  rubric: RubricOut | null;
  assignment_title: string | null;
  max_points: number | null;
  attempts: { id: string; attempt_number: number; submitted_at: string; is_late: boolean }[];
}

export interface StartAssignmentOut {
  notebook_id: string;
  title: string;
  url: string;
  created: boolean;
}

export interface GradeListResponse {
  grades: GradeOut[];
}

export interface MyGradeOut {
  submission_id: string;
  assignment_id: string;
  assignment_title: string;
  course_id: string;
  attempt_number: number;
  is_late: boolean;
  final_score: number | null;
  max_points: number;
  published_at: string | null;
  revision: number | null;
  feedback?: string;
}

export interface MyGradesResponse {
  grades: MyGradeOut[];
}

export interface CompletionOut {
  assigned: number;
  submitted: number;
  graded: number;
}

export interface ScoreTrendItem {
  assignment_id: string;
  title: string;
  score: number | null;
  date: string | null;
}

export interface StudentScores {
  average: number | null;
  best: number | null;
  trend: ScoreTrendItem[];
}

export interface CriterionMastery {
  key: string;
  label: string;
  earned: number;
  max: number;
  percent: number | null;
}

export interface TimeOnTaskRow {
  assignment_id: string;
  title: string;
  seconds: number;
}

export interface StudentAssignmentRow {
  id: string;
  title: string;
  status: string;
  final_score: number | null;
  max_points: number;
  is_late: boolean;
  due_at: string | null;
}

export interface StudentDashboard {
  course_id: string | null;
  completion: CompletionOut;
  scores: StudentScores;
  criteria: CriterionMastery[];
  time_on_task_seconds: number;
  time_on_task: TimeOnTaskRow[];
  late_count: number;
  ungraded_count: number;
  assignments: StudentAssignmentRow[];
}

export interface SubmissionDetail {
  submission_id: string;
  assignment_id: string;
  assignment_title: string;
  attempt_number: number;
  status: string;
  is_late: boolean;
  final_score: number | null;
  max_points: number;
  submitted_at: string;
  graded_at: string | null;
  grade_revision: number | null;
  published_at: string | null;
}

export interface StudentDrilldown extends StudentDashboard {
  student: { id: string; display_name: string; email: string } | null;
  submissions: SubmissionDetail[];
}

export interface TeacherSummary {
  students: number;
  completion_rate: number;
  average_score: number | null;
  late_rate: number;
  ungraded: number;
}

export interface TeacherAssignmentRow {
  id: string;
  title: string;
  max_points: number;
  due_at: string | null;
  submitted: number;
  graded: number;
  average_score: number | null;
  distribution: Record<string, number>;
}

export interface TeacherCriterionRow {
  key: string;
  label: string;
  average_percent: number | null;
}

export interface TeacherDashboard {
  course_id: string;
  summary: TeacherSummary;
  assignments: TeacherAssignmentRow[];
  criteria: TeacherCriterionRow[];
  roster: RosterRow[];
  roster_total: number;
  roster_limit: number;
  roster_offset: number;
}

// --- classes, people ----------------------------------------------------
export interface CourseInput {
  name?: string;
  code?: string;
  term?: string;
  description?: string;
  status?: "active" | "archived";
}

export interface MemberOut {
  user_id: string;
  email: string;
  display_name: string;
  role_in_course: CourseRole;
  joined_at: string | null;
}

export interface AddMembersResponse {
  added: MemberOut[];
  updated: MemberOut[];
  unknown: string[];
}

// --- stream -------------------------------------------------------------
export type AttachmentKind = "link" | "dataset" | "lesson" | "exercise" | "assignment";

export interface AttachmentInput {
  kind: AttachmentKind;
  target: string;
  label?: string;
}

export interface AttachmentOut {
  id: string;
  kind: string;
  label: string;
  url: string | null;
  internal: boolean;
}

export interface PostOut {
  id: string;
  course_id: string;
  kind: "announcement" | "material";
  title: string;
  body: string;
  topic: string | null;
  is_pinned: boolean;
  status: "draft" | "published";
  publish_at: string | null;
  published_at: string | null;
  edited_at: string | null;
  created_at: string;
  author: { id: string; display_name: string } | null;
  attachments: AttachmentOut[];
  is_read: boolean;
  can_edit: boolean;
  read_count: number | null;
  audience: number | null;
}

export interface PostInput {
  kind?: "announcement" | "material";
  title?: string;
  body?: string;
  topic?: string | null;
  is_pinned?: boolean;
  status?: "draft" | "published";
  publish_at?: string | null;
  attachments?: AttachmentInput[];
}

export interface PostListResponse {
  posts: PostOut[];
  next_cursor: string | null;
}

export interface ReadersResponse {
  read: { user_id: string; display_name: string; read_at: string | null }[];
  unread: { user_id: string; display_name: string; read_at: string | null }[];
}

// --- notifications, home, teaching ---------------------------------------
export interface NotificationOut {
  id: string;
  kind: string;
  course_id: string | null;
  title: string;
  link: string;
  created_at: string;
  read_at: string | null;
}

export interface GradebookCell {
  assignment_id: string;
  submission_id: string | null;
  state: "returned" | "draft" | "submitted" | "missing" | "not_submitted";
  score: number | null;
  is_late: boolean;
}

export interface Gradebook {
  course_id: string;
  assignments: { id: string; title: string; max_points: number; weight: number; due_at: string | null; is_visible: boolean }[];
  rows: { user_id: string; display_name: string; email: string; cells: GradebookCell[]; weighted_percent: number | null }[];
}

export interface QueueRow {
  assignment_id: string;
  assignment_title: string;
  course_id: string;
  course_code: string;
  due_at: string | null;
  ungraded: number;
  drafts: number;
  late: number;
}

export interface StudentHome {
  courses: { id: string; code: string; name: string; status: string }[];
  due_soon: { assignment_id: string; title: string; course_id: string; course_code: string; due_at: string | null; is_overdue: boolean }[];
  posts: { id: string; course_id: string; course_code: string; kind: string; title: string; excerpt: string; is_read: boolean; published_at: string }[];
  feedback: { submission_id: string; assignment_id: string; assignment_title: string; course_id: string; final_score: number | null; max_points: number; released_at: string | null; has_comments: boolean }[];
}

/** Minimal nbformat v4 shape used by the read-only notebook viewer. */
export interface NotebookDocument {
  cells?: NotebookCell[];
  metadata?: Record<string, unknown>;
  nbformat?: number;
}

export interface NotebookCell {
  cell_type: "code" | "markdown" | "raw";
  source: string | string[];
  execution_count?: number | null;
  outputs?: NotebookOutput[];
}

export interface NotebookOutput {
  output_type: "stream" | "execute_result" | "display_data" | "error";
  name?: string;
  text?: string | string[];
  data?: Record<string, string | string[]>;
  ename?: string;
  evalue?: string;
  traceback?: string[];
  execution_count?: number | null;
}
