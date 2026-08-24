"use client";
import { useEffect, useState } from "react";
import { useAuth, SessionRecord } from "@/components/AuthProvider";
import { Shield, MonitorSmartphone, MapPin, Clock, CheckCircle2, XCircle, LogOut, X, Loader2, Trash2 } from "lucide-react";

export default function SessionsModal({ onClose }: { onClose: () => void }) {
  const { getSessions, revokeSession, logoutAll } = useAuth();
  const [sessions, setSessions] = useState<SessionRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [revoking, setRevoking] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    const data = await getSessions();
    setSessions(data);
    setLoading(false);
  };

  useEffect(() => { load(); }, []);

  const handleRevoke = async (sessionId: string) => {
    if (!confirm("Sign out of this session?")) return;
    setRevoking(sessionId);
    await revokeSession(sessionId);
    await load();
    setRevoking(null);
  };

  const handleLogoutAll = async () => {
    if (!confirm("Sign out of ALL sessions including this one?")) return;
    await logoutAll();
  };

  const formatDate = (iso: string | null) => {
    if (!iso) return "—";
    return new Date(iso).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" });
  };

  const activeSessions  = sessions.filter(s => s.status === "active");
  const endedSessions   = sessions.filter(s => s.status === "ended");

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm px-4">
      <div className="bg-white dark:bg-slate-900 rounded-2xl shadow-2xl w-full max-w-2xl border border-slate-200 dark:border-slate-700 max-h-[90vh] flex flex-col">

        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200 dark:border-slate-700">
          <div className="flex items-center gap-3">
            <div className="h-9 w-9 rounded-xl bg-emerald-100 dark:bg-emerald-900/30 flex items-center justify-center">
              <Shield className="h-5 w-5 text-emerald-600 dark:text-emerald-400" />
            </div>
            <div>
              <h2 className="text-base font-bold text-slate-800 dark:text-slate-100">Active Sessions</h2>
              <p className="text-xs text-slate-500 dark:text-slate-400">Devices logged into your account</p>
            </div>
          </div>
          <button onClick={onClose} className="h-8 w-8 rounded-lg flex items-center justify-center text-slate-400 dark:text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors">
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Body */}
        <div className="overflow-y-auto flex-1 px-6 py-4 space-y-4">
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-6 w-6 animate-spin text-violet-400" />
            </div>
          ) : (
            <>
              {/* Active sessions */}
              <div>
                <h3 className="text-xs font-bold uppercase tracking-widest text-slate-400 dark:text-slate-500 mb-2">
                  Active ({activeSessions.length})
                </h3>
                {activeSessions.length === 0 ? (
                  <p className="text-sm text-slate-500 italic">No active sessions found.</p>
                ) : (
                  <div className="space-y-2">
                    {activeSessions.map(s => (
                      <div key={s.session_id} className="flex items-start gap-3 p-3 rounded-xl border border-emerald-200 dark:border-emerald-800/40 bg-emerald-50/50 dark:bg-emerald-900/10">
                        <div className="h-9 w-9 rounded-lg bg-emerald-100 dark:bg-emerald-900/30 flex items-center justify-center flex-shrink-0 mt-0.5">
                          <MonitorSmartphone className="h-4 w-4 text-emerald-600 dark:text-emerald-400" />
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 mb-1">
                            <span className="text-sm font-semibold text-slate-800 dark:text-slate-100 truncate">{s.device_info}</span>
                            <span className="flex-shrink-0 inline-flex items-center gap-1 text-[10px] font-bold px-1.5 py-0.5 rounded-full bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-400">
                              <CheckCircle2 className="h-2.5 w-2.5" /> Active
                            </span>
                          </div>
                          <div className="flex flex-wrap gap-x-4 gap-y-0.5 text-xs text-slate-500 dark:text-slate-400">
                            <span className="flex items-center gap-1"><MapPin className="h-3 w-3" />{s.ip_address || "Unknown IP"}</span>
                            <span className="flex items-center gap-1"><Clock className="h-3 w-3" />Last active: {formatDate(s.last_active)}</span>
                            <span>Started: {formatDate(s.created_at)}</span>
                          </div>
                        </div>
                        <button
                          onClick={() => handleRevoke(s.session_id)}
                          disabled={revoking === s.session_id}
                          className="flex-shrink-0 flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs font-semibold text-rose-600 dark:text-rose-400 bg-rose-50 dark:bg-rose-900/20 hover:bg-rose-100 dark:hover:bg-rose-900/40 transition-colors disabled:opacity-50"
                        >
                          {revoking === s.session_id ? <Loader2 className="h-3 w-3 animate-spin" /> : <LogOut className="h-3 w-3" />}
                          Revoke
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Session history */}
              {endedSessions.length > 0 && (
                <div>
                  <h3 className="text-xs font-bold uppercase tracking-widest text-slate-400 dark:text-slate-500 mb-2">
                    History (last {endedSessions.length})
                  </h3>
                  <div className="space-y-1.5">
                    {endedSessions.map(s => (
                      <div key={s.session_id} className="flex items-start gap-3 p-3 rounded-xl border border-slate-100 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-800/20 opacity-60">
                        <div className="h-8 w-8 rounded-lg bg-slate-100 dark:bg-slate-800 flex items-center justify-center flex-shrink-0">
                          <MonitorSmartphone className="h-3.5 w-3.5 text-slate-400 dark:text-slate-500" />
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 mb-0.5">
                            <span className="text-xs font-semibold text-slate-600 dark:text-slate-300 truncate">{s.device_info}</span>
                            <span className="flex-shrink-0 inline-flex items-center gap-1 text-[10px] font-bold px-1.5 py-0.5 rounded-full bg-slate-100 dark:bg-slate-700 text-slate-500 dark:text-slate-400">
                              <XCircle className="h-2.5 w-2.5" /> Ended
                            </span>
                          </div>
                          <div className="flex flex-wrap gap-x-4 text-xs text-slate-400 dark:text-slate-500">
                            <span>{s.ip_address || "Unknown IP"}</span>
                            <span>Ended: {formatDate(s.ended_at)}</span>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-slate-200 dark:border-slate-700 flex items-center justify-between">
          <p className="text-xs text-slate-400 dark:text-slate-500">Sessions expire after 24 hours of inactivity</p>
          <button
            onClick={handleLogoutAll}
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-rose-500 hover:bg-rose-600 text-white text-xs font-bold transition-colors shadow-sm"
          >
            <LogOut className="h-3.5 w-3.5" /> Sign Out All Devices
          </button>
        </div>
      </div>
    </div>
  );
}
