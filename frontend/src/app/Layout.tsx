import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "../app/AuthContext";
import { Badge } from "../components/ui";

const navItems = [
  { to: "/learn", label: "Learn", icon: "◈" },
  { to: "/practice", label: "Practice", icon: "◎" },
  { to: "/notebooks", label: "Notebooks", icon: "▤" },
  { to: "/datasets", label: "Datasets", icon: "▦" },
  { to: "/dashboard", label: "Dashboard", icon: "◫" },
  { to: "/teaching", label: "Teaching", icon: "▥" },
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
  const { user, signOut } = useAuth();
  const navigate = useNavigate();

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

        <nav className="nav" aria-label="Primary">
          {navItems.map((item) => (
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
          ))}
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
                  <div className="small dim">{user.role}</div>
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
          </div>
        </header>
        <main className="page">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
