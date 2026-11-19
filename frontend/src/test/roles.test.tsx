import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { AuthProvider } from "../app/AuthContext";
import { AppRoutes } from "../app/routes";

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const base = { email: "x@opencs.local", hub_username: "x", preferences: {} };
const teacher = {
  ...base,
  id: "t1",
  display_name: "Tara Teacher",
  role: "instructor",
  teaching: { is_teacher: true, staff_course_count: 1, student_course_count: 0, can_create_courses: true },
};
const student = {
  ...base,
  id: "s1",
  display_name: "Sam Student",
  role: "student",
  teaching: { is_teacher: false, staff_course_count: 0, student_course_count: 1, can_create_courses: false },
};
const course = (role: string) => ({
  id: "c1", name: "Data Wrangling", code: "DW-201", term: "2027", status: "active",
  description: "", role_in_course: role, join_code: role === "instructor" ? "ABC2345" : null,
});

/** Order matters: more specific prefixes first (matching is by substring). */
function stub(me: object, role: string) {
  const routes: [string, () => Response][] = [
    ["/api/v1/me/notifications/count", () => json({ unread: 3 })],
    ["/api/v1/me/home", () => json({ courses: [], due_soon: [], posts: [], feedback: [] })],
    ["/api/v1/me", () => json(me)],
    ["/api/v1/teaching/queue", () => json({ items: [] })],
    ["/api/v1/courses/c1/posts", () => json({ posts: [], next_cursor: null })],
    ["/api/v1/courses/c1/assignments", () => json({ assignments: [] })],
    ["/api/v1/courses/c1", () => json(course(role))],
    ["/api/v1/courses", () => json({ courses: [course(role)] })],
  ];
  return vi.fn(async (input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input.toString();
    for (const [prefix, handler] of routes) if (url.includes(prefix)) return handler();
    return json({ error: { code: "NOT_STUBBED", message: url } }, 404);
  });
}

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <AppRoutes />
      </AuthProvider>
    </MemoryRouter>,
  );
}

describe("distinct teacher and student experiences", () => {
  beforeEach(() => vi.restoreAllMocks());
  afterEach(() => vi.unstubAllGlobals());

  it("teacher lands on Classes with teaching navigation and no student-only links", async () => {
    vi.stubGlobal("fetch", stub(teacher, "instructor"));
    renderAt("/");
    await waitFor(() => expect(screen.getByRole("heading", { name: "Classes you teach" })).toBeInTheDocument());
    const nav = screen.getByRole("navigation", { name: "Primary" });
    expect(nav).toHaveTextContent("To grade");
    expect(nav).not.toHaveTextContent("Progress");
    expect(nav).not.toHaveTextContent("Home");
    expect(screen.getByRole("button", { name: "+ Create class" })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByLabelText("Notifications (3 unread)")).toBeInTheDocument());
  });

  it("student lands on Home and cannot reach teacher routes", async () => {
    vi.stubGlobal("fetch", stub(student, "student"));
    renderAt("/to-grade");
    await waitFor(() => expect(screen.getByRole("heading", { name: /Welcome back, Sam/ })).toBeInTheDocument());
    const nav = screen.getByRole("navigation", { name: "Primary" });
    expect(nav).toHaveTextContent("Progress");
    expect(nav).not.toHaveTextContent("To grade");
  });

  it("class tabs follow the role in that class", async () => {
    vi.stubGlobal("fetch", stub(teacher, "instructor"));
    const { unmount } = renderAt("/classes/c1/stream");
    await waitFor(() => expect(screen.getByRole("heading", { name: "Data Wrangling" })).toBeInTheDocument());
    let tabs = screen.getByRole("navigation", { name: "Sections" });
    for (const label of ["Stream", "Classwork", "People", "Grades", "Insights"]) expect(tabs).toHaveTextContent(label);
    expect(screen.getByText("ABC2345")).toBeInTheDocument();
    unmount();

    vi.stubGlobal("fetch", stub(student, "student"));
    renderAt("/classes/c1/people");
    // Staff-only tab redirects a student back to the stream.
    await waitFor(() => expect(screen.getByRole("heading", { name: "Data Wrangling" })).toBeInTheDocument());
    tabs = screen.getByRole("navigation", { name: "Sections" });
    expect(tabs).toHaveTextContent("My grades");
    expect(tabs).not.toHaveTextContent("People");
    expect(screen.queryByText("ABC2345")).toBeNull();
    await waitFor(() => expect(screen.getByText("Nothing posted yet")).toBeInTheDocument());
  });

  it("legacy routes redirect to the new experience", async () => {
    vi.stubGlobal("fetch", stub(teacher, "instructor"));
    renderAt("/teaching");
    await waitFor(() => expect(screen.getByRole("heading", { name: "Classes you teach" })).toBeInTheDocument());
  });
});
