import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../app/AuthContext";
import { Badge } from "../components/ui";
import { NotificationBell } from "../features/notifications/NotificationBell";

type NavItem = { to: string; label: string; icon: string } | { section: string };

// Two distinct experiences (ADR-010). Teachers never see student-only flows
// (turn-in, progress); students never see teaching tools.
const TEACHER_NAV: NavItem[] = [
  { to: "/classes", label: "Classes", icon: "▥" },
  { to: "/to-grade", label: "To grade", icon: "✓" },
  { to: "/notebooks", label: "My notebooks", icon: "▤" },
  { section: "Library" },
  { to: "/learn", label: "Lessons", icon: "◈" },
  { to: "/practice", label: "Exercises", icon: "◎" },
  { to: "/datasets", label: "Datasets", icon: "▦" },
];

const STUDENT_NAV: NavItem[] = [
  { to: "/home", label: "Home", icon: "⌂" },
  { to: "/classes", label: "Classes", icon: "▥" },
  { to: "/learn", label: "Learn", icon: "◈" },
  { to: "/practice", label: "Practice", icon: "◎" },
  { to: "/notebooks", label: "Notebooks", icon: "▤" },
  { to: "/datasets", label: "Datasets", icon: "▦" },
  { to: "/progress", label: "Progress", icon: "◫" },
];

function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("");
}

export function Layout() {
  const { user, signOut, mode, setMode, canSwitch } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const navItems = mode === "teach" ? TEACHER_NAV : STUDENT_NAV;
  const previewing = mode === "teach" && /^\/(learn|practice)/.test(location.pathname);

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">O</span>
          <div>
            <div style={{ lineHeight: 1.1 }}>OpenCS Labs</div>
            <div className="small dim" style={{ fontWeight: 500 }}>
              Data Analysis
            </div>
          </div>
        </div>

        {canSwitch && (
          <div className="mode-switch" role="group" aria-label="Experience">
            {(["teach", "learn"] as const).map((m) => (
              <button
                key={m}
                type="button"
                className={mode === m ? "active" : ""}
                onClick={() => {
                  setMode(m);
                  navigate(m === "teach" ? "/classes" : "/home");
                }}
              >
                {m === "teach" ? "Teaching" : "Learning"}
              </button>
            ))}
          </div>
        )}

        <nav className="nav" aria-label="Primary">
          {navItems.map((item) =>
            "section" in item ? (
              <div key={item.section} className="nav-section">
                {item.section}
              </div>
            ) : (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}
            >
              <span aria-hidden style={{ width: 16, textAlign: "center" }}>
                {item.icon}
              </span>
              {item.label}
            </NavLink>
            ),
          )}
        </nav>

        <div className="sidebar-foot">
          {user ? (
            <div className="stack-sm">
              <div className="row" style={{ gap: 9 }}>
                <span className="avatar">{initials(user.display_name)}</span>
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontWeight: 600, fontSize: 13, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                    {user.display_name}
                  </div>
                  <div className="small dim">{mode === "teach" ? "Teacher" : "Student"}</div>
                </div>
              </div>
              <button
                className="btn btn-ghost btn-sm btn-block"
                type="button"
                onClick={async () => {
                  await signOut();
                  navigate("/login");
                }}
              >
                Sign out
              </button>
            </div>
          ) : (
            <NavLink to="/login" className="btn btn-primary btn-sm btn-block">
              Sign in
            </NavLink>
          )}
        </div>
      </aside>

      <div className="main">
        <header className="topbar">
          <div className="row" style={{ gap: 10 }}>
            <span className="dim small">OpenCS Labs</span>
            <span className="dim small">/</span>
            <span className="small" style={{ fontWeight: 600 }}>
              Data Analysis & Data Science
            </span>
          </div>
          <div className="row" style={{ gap: 10 }}>
            <Badge tone="green">Pinned environment</Badge>
            {user && <Badge tone="accent">{user.hub_username}</Badge>}
            {user && <NotificationBell />}
          </div>
        </header>
        <main className="page">
          {previewing && (
            <div className="notice notice-info small" style={{ marginBottom: 16 }}>
              Teacher preview: this is the student-facing library. Attach lessons, exercises and datasets to a class from its Stream or Classwork.
            </div>
          )}
          <Outlet />
        </main>
      </div>
    </div>
  );
}
