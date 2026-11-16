import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { AuthProvider } from "../app/AuthContext";
import { AppRoutes } from "../app/routes";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const student = {
  id: "11111111-1111-1111-1111-111111111111",
  email: "student@opencs.local",
  display_name: "Maya Student",
  role: "student",
  hub_username: "student1",
  preferences: { theme: "dark" },
};

function stubApi(paths: Record<string, () => Response>) {
  return vi.fn(async (input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input.toString();
    for (const [prefix, handler] of Object.entries(paths)) {
      if (url.includes(prefix)) return handler();
    }
    return jsonResponse({ error: { code: "NOT_STUBBED", message: url } }, 404);
  });
}

describe("app shell", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows the login screen when there is no session", async () => {
    vi.stubGlobal(
      "fetch",
      stubApi({
        "/api/v1/me": () => jsonResponse({ error: { code: "UNAUTHENTICATED", message: "no" } }, 401),
        "/api/v1/auth/mode": () => jsonResponse({ mode: "dev" }),
      }),
    );

    render(
      <MemoryRouter initialEntries={["/learn"]}>
        <AuthProvider>
          <AppRoutes />
        </AuthProvider>
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    });
  });

  it("renders the learning catalogue for a signed-in student", async () => {
    vi.stubGlobal(
      "fetch",
      stubApi({
        "/api/v1/me": () => jsonResponse(student),
        "/api/v1/learning/paths": () =>
          jsonResponse({
            paths: [
              {
                slug: "data-analysis",
                title: "Data Analysis & Data Science",
                description: "A beginner-first path.",
                modules: [
                  {
                    slug: "introduction",
                    title: "Introduction",
                    description: "Start here.",
                    position: 1,
                    total_lessons: 1,
                    completed_lessons: 0,
                    lessons: [
                      {
                        slug: "welcome",
                        title: "Welcome to Data Analysis",
                        summary: "Your first lesson.",
                        objective: "Understand the workflow.",
                        estimated_minutes: 10,
                        position: 1,
                        status: "not_started",
                        dataset_slugs: ["iris"],
                        exercise_slugs: [],
                        has_notebook_activity: true,
                      },
                    ],
                  },
                ],
                total_lessons: 1,
                completed_lessons: 0,
                progress_percent: 0,
              },
            ],
            total_lessons: 1,
            completed_lessons: 0,
          }),
      }),
    );

    render(
      <MemoryRouter initialEntries={["/learn"]}>
        <AuthProvider>
          <AppRoutes />
        </AuthProvider>
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText("Welcome to Data Analysis")).toBeInTheDocument();
    });
    expect(screen.getByText("Introduction")).toBeInTheDocument();
  });
});
