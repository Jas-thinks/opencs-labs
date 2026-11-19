import { createContext, useContext } from "react";
import { Navigate, Outlet, useParams } from "react-router-dom";
import { api } from "../../api/client";
import type { CourseOut } from "../../api/types";
import { useAsync } from "../../app/useAsync";
import { Badge, Empty, ErrorBox, Loading } from "../../components/ui";
import { RouteTabs } from "../../components/kit";
import { isStaffRole } from "./ClassesPage";

interface CourseContextValue {
  course: CourseOut;
  isStaff: boolean;
  isInstructor: boolean;
  reload: () => void;
}

const CourseContext = createContext<CourseContextValue | null>(null);

export function useCourse(): CourseContextValue {
  const value = useContext(CourseContext);
  if (!value) throw new Error("useCourse must be used inside CourseShell");
  return value;
}

/**
 * One class, Classroom-style. Tabs depend on the viewer's role *in this class*
 * (a TA who is a student elsewhere sees the student tabs there).
 */
export function CourseShell() {
  const { courseId = "" } = useParams();
  const course = useAsync(() => api.course(courseId), [courseId]);

  if (course.loading) return <Loading label="Loading class…" />;
  if (course.error) return <ErrorBox error={course.error} retry={course.reload} />;
  const data = course.data;
  if (!data) return null;

  const isStaff = isStaffRole(data.role_in_course);
  const isInstructor = ["instructor", "admin", "staff"].includes(data.role_in_course);
  const base = `/classes/${data.id}`;
  const tabs = isStaff
    ? [
        { to: `${base}/stream`, label: "Stream" },
        { to: `${base}/classwork`, label: "Classwork" },
        { to: `${base}/people`, label: "People" },
        { to: `${base}/grades`, label: "Grades" },
        { to: `${base}/insights`, label: "Insights" },
      ]
    : [
        { to: `${base}/stream`, label: "Stream" },
        { to: `${base}/classwork`, label: "Classwork" },
        { to: `${base}/grades`, label: "My grades" },
      ];

  return (
    <CourseContext.Provider value={{ course: data, isStaff, isInstructor, reload: course.reload }}>
      <div className="stack" style={{ gap: 0 }}>
        <header className="class-banner">
          <div>
            <div className="mono small">{data.code} · {data.term}</div>
            <h1 style={{ margin: "4px 0 0" }}>{data.name}</h1>
            {data.description && <p className="small" style={{ margin: "6px 0 0", opacity: 0.85 }}>{data.description}</p>}
          </div>
          <div className="stack-sm" style={{ alignItems: "flex-end" }}>
            {data.status === "archived" && <Badge tone="neutral">archived · read-only</Badge>}
            {isInstructor && data.join_code && (
              <div className="join-code" title="Students join with this code">
                <span className="small">Class code</span>
                <span className="mono">{data.join_code}</span>
              </div>
            )}
          </div>
        </header>
        <RouteTabs tabs={tabs} />
        <Outlet />
      </div>
    </CourseContext.Provider>
  );
}

/** Route guard for staff-only class tabs: students get a not-found page. */
export function StaffOnly({ children }: { children: React.ReactNode }) {
  const { isStaff, course } = useCourse();
  if (!isStaff) return <Navigate to={`/classes/${course.id}/stream`} replace />;
  return <>{children}</>;
}

export function NotFoundPanel() {
  return <Empty title="Not found">This page does not exist or you do not have access to it.</Empty>;
}
