import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { api, onUnauthorized } from "../api/client";
import type { UserOut } from "../api/types";

export type Mode = "teach" | "learn";

interface AuthContextValue {
  user: UserOut | null;
  loading: boolean;
  /** Teacher experience available (server-computed; see ADR-010). */
  isTeacher: boolean;
  /** Also a student somewhere: can switch to the learning experience. */
  canSwitch: boolean;
  mode: Mode;
  setMode: (mode: Mode) => void;
  signIn: (email: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserOut | null>(null);
  const [loading, setLoading] = useState(true);
  const [storedMode, setStoredMode] = useState<Mode | null>(null);

  const isTeacher = Boolean(user?.teaching?.is_teacher);
  const canSwitch = isTeacher && (user?.teaching?.student_course_count ?? 0) > 0;
  const modeKey = user ? `opencs.mode.${user.id}` : null;

  useEffect(() => {
    if (!modeKey) return;
    try {
      const saved = window.localStorage.getItem(modeKey);
      setStoredMode(saved === "teach" || saved === "learn" ? saved : null);
    } catch {
      setStoredMode(null);
    }
  }, [modeKey]);

  const mode: Mode = !isTeacher ? "learn" : canSwitch && storedMode === "learn" ? "learn" : "teach";

  const setMode = useCallback(
    (next: Mode) => {
      setStoredMode(next);
      if (!modeKey) return;
      try {
        window.localStorage.setItem(modeKey, next);
      } catch {
        // Private mode / blocked storage: the switch still works for this session.
      }
    },
    [modeKey],
  );

  const refresh = useCallback(async () => {
    try {
      const me = await api.me();
      setUser(me);
    } catch {
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    onUnauthorized(() => setUser(null));
  }, [refresh]);

  const signIn = useCallback(async (email: string, password: string) => {
    const result = await api.login(email, password);
    setUser(result.user);
  }, []);

  const signOut = useCallback(async () => {
    try {
      await api.logout();
    } finally {
      setUser(null);
    }
  }, []);

  const value = useMemo(
    () => ({ user, loading, isTeacher, canSwitch, mode, setMode, signIn, signOut, refresh }),
    [user, loading, isTeacher, canSwitch, mode, setMode, signIn, signOut, refresh],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used inside AuthProvider");
  }
  return context;
}
