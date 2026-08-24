"use client";

import React, { createContext, useContext, useEffect, useState } from "react";
import { useRouter, usePathname } from "next/navigation";

interface User {
  id: number;
  email: string;
  role: string;
}

export interface SessionRecord {
  session_id: string;
  ip_address: string;
  device_info: string;
  status: "active" | "ended";
  created_at: string;
  last_active: string;
  ended_at: string | null;
}

interface AuthContextType {
  user: User | null;
  loading: boolean;
  refreshUser: () => Promise<void>;
  logout: () => Promise<void>;
  logoutAll: () => Promise<void>;
  getSessions: () => Promise<SessionRecord[]>;
  revokeSession: (sessionId: string) => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const router = useRouter();
  const pathname = usePathname();

  const refreshUser = async () => {
    try {
      const res = await fetch("/api/auth/me");
      if (res.ok) {
        const data = await res.json();
        setUser(data);
      } else {
        setUser(null);
      }
    } catch {
      setUser(null);
    } finally {
      setLoading(false);
    }
  };

  const logout = async () => {
    await fetch("/api/auth/logout", { method: "POST" });
    setUser(null);
    router.push("/login");
  };

  const logoutAll = async () => {
    await fetch("/api/auth/logout-all", { method: "POST" });
    setUser(null);
    router.push("/login");
  };

  const getSessions = async (): Promise<SessionRecord[]> => {
    const res = await fetch("/api/auth/sessions");
    if (!res.ok) return [];
    const data = await res.json();
    return data.sessions || [];
  };

  const revokeSession = async (sessionId: string) => {
    await fetch(`/api/auth/sessions/${sessionId}`, { method: "DELETE" });
  };

  useEffect(() => {
    refreshUser();
  }, []);

  useEffect(() => {
    if (!loading && !user && pathname !== "/login") {
      router.push("/login");
    }
  }, [user, loading, pathname, router]);

  return (
    <AuthContext.Provider value={{ user, loading, refreshUser, logout, logoutAll, getSessions, revokeSession }}>
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
};
