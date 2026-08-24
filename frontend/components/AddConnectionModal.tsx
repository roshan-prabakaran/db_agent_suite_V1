"use client";
import { useState } from "react";
import { X, Database, Server, Key, Loader2, AlertCircle } from "lucide-react";

interface AddConnectionModalProps {
  onClose: () => void;
  onAdded: () => void;
}

export default function AddConnectionModal({ onClose, onAdded }: AddConnectionModalProps) {
  const [form, setForm] = useState({ name: "", host: "", port: "5432", database: "", user: "", password: "" });
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const set = (k: string, v: string) => { setForm(f => ({ ...f, [k]: v })); setError(""); };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true); setError("");
    try {
      const res = await fetch("/api/connections", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(form),
      });
      const data = await res.json();
      if (res.ok) { onAdded(); onClose(); }
      else setError(data.detail || "Failed to add connection");
    } catch { setError("Network error. Please try again."); }
    finally { setLoading(false); }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
      <div className="w-full max-w-md rounded-2xl bg-white dark:bg-slate-800 shadow-2xl border border-slate-200 dark:border-slate-700 overflow-hidden">
        {/* Header */}
        <div className="px-6 py-5 border-b border-slate-100 dark:border-slate-700 bg-gradient-to-r from-violet-50 to-slate-50 dark:from-slate-800 dark:to-slate-800">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="h-9 w-9 rounded-xl bg-violet-500 flex items-center justify-center shadow-sm">
                <Database className="h-4 w-4 text-white" />
              </div>
              <div>
                <h2 className="text-base font-bold text-slate-800 dark:text-slate-100">Add Database Connection</h2>
                <p className="text-xs text-slate-500 dark:text-slate-400">Connect a PostgreSQL database</p>
              </div>
            </div>
            <button onClick={onClose} className="h-7 w-7 rounded-md flex items-center justify-center text-slate-400 hover:bg-slate-200 dark:hover:bg-slate-700 hover:text-slate-600 dark:hover:text-slate-300 transition-colors">
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          {error && (
            <div className="flex items-start gap-2 rounded-lg bg-rose-50 dark:bg-rose-900/20 border border-rose-200 dark:border-rose-800 px-3 py-2.5">
              <AlertCircle className="h-4 w-4 text-rose-500 mt-0.5 flex-shrink-0" />
              <p className="text-sm text-rose-700 dark:text-rose-400">{error}</p>
            </div>
          )}

          {/* Connection Name */}
          <div>
            <label className="block text-xs font-semibold text-slate-600 dark:text-slate-400 mb-1.5">Connection Name</label>
            <input type="text" placeholder="e.g. My Prod DB" value={form.name} onChange={e => set("name", e.target.value)}
              className="w-full rounded-lg border border-slate-200 dark:border-slate-600 bg-slate-50 dark:bg-slate-700 px-3 py-2.5 text-sm text-slate-800 dark:text-slate-100 placeholder-slate-400 dark:placeholder-slate-500 focus:border-violet-400 focus:bg-white dark:focus:bg-slate-600 focus:outline-none focus:ring-2 focus:ring-violet-400/20 transition-all" required />
          </div>

          {/* Host + Port row */}
          <div className="grid grid-cols-3 gap-3">
            <div className="col-span-2">
              <label className="block text-xs font-semibold text-slate-600 dark:text-slate-400 mb-1.5">Host</label>
              <div className="relative">
                <Server className="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-slate-400" />
                <input type="text" placeholder="db.example.com" value={form.host} onChange={e => set("host", e.target.value)}
                  className="w-full rounded-lg border border-slate-200 dark:border-slate-600 bg-slate-50 dark:bg-slate-700 pl-8 pr-3 py-2.5 text-sm text-slate-800 dark:text-slate-100 placeholder-slate-400 dark:placeholder-slate-500 focus:border-violet-400 focus:bg-white dark:focus:bg-slate-600 focus:outline-none focus:ring-2 focus:ring-violet-400/20 transition-all" required />
              </div>
            </div>
            <div>
              <label className="block text-xs font-semibold text-slate-600 dark:text-slate-400 mb-1.5">Port</label>
              <input type="text" placeholder="5432" value={form.port} onChange={e => set("port", e.target.value)}
                className="w-full rounded-lg border border-slate-200 dark:border-slate-600 bg-slate-50 dark:bg-slate-700 px-3 py-2.5 text-sm text-slate-800 dark:text-slate-100 placeholder-slate-400 dark:placeholder-slate-500 focus:border-violet-400 focus:bg-white dark:focus:bg-slate-600 focus:outline-none focus:ring-2 focus:ring-violet-400/20 transition-all" required />
            </div>
          </div>

          {/* Database */}
          <div>
            <label className="block text-xs font-semibold text-slate-600 dark:text-slate-400 mb-1.5">Database Name</label>
            <input type="text" placeholder="mydb" value={form.database} onChange={e => set("database", e.target.value)}
              className="w-full rounded-lg border border-slate-200 dark:border-slate-600 bg-slate-50 dark:bg-slate-700 px-3 py-2.5 text-sm text-slate-800 dark:text-slate-100 placeholder-slate-400 dark:placeholder-slate-500 focus:border-violet-400 focus:bg-white dark:focus:bg-slate-600 focus:outline-none focus:ring-2 focus:ring-violet-400/20 transition-all" required />
          </div>

          {/* Username + Password */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-semibold text-slate-600 dark:text-slate-400 mb-1.5">Username</label>
              <input type="text" placeholder="roshanprabhakaran80@gmail.com" value={form.user} onChange={e => set("user", e.target.value)}
                className="w-full rounded-lg border border-slate-200 dark:border-slate-600 bg-slate-50 dark:bg-slate-700 px-3 py-2.5 text-sm text-slate-800 dark:text-slate-100 placeholder-slate-400 dark:placeholder-slate-500 focus:border-violet-400 focus:bg-white dark:focus:bg-slate-600 focus:outline-none focus:ring-2 focus:ring-violet-400/20 transition-all" required />
            </div>
            <div>
              <label className="block text-xs font-semibold text-slate-600 dark:text-slate-400 mb-1.5">Password</label>
              <div className="relative">
                <Key className="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-slate-400" />
                <input type="password" placeholder="••••••••" value={form.password} onChange={e => set("password", e.target.value)}
                  className="w-full rounded-lg border border-slate-200 dark:border-slate-600 bg-slate-50 dark:bg-slate-700 pl-8 pr-3 py-2.5 text-sm text-slate-800 dark:text-slate-100 placeholder-slate-400 dark:placeholder-slate-500 focus:border-violet-400 focus:bg-white dark:focus:bg-slate-600 focus:outline-none focus:ring-2 focus:ring-violet-400/20 transition-all" required />
              </div>
            </div>
          </div>

          {/* Buttons */}
          <div className="flex gap-3 pt-1">
            <button type="button" onClick={onClose} className="flex-1 rounded-lg border border-slate-200 dark:border-slate-600 py-2.5 text-sm font-medium text-slate-600 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-700 transition-colors">
              Cancel
            </button>
            <button type="submit" disabled={loading} className="flex-1 rounded-lg bg-blue-600 hover:bg-blue-700 py-2.5 text-sm font-semibold text-white transition-colors shadow-sm shadow-blue-200 disabled:opacity-50 flex items-center justify-center gap-2">
              {loading ? <><Loader2 className="h-4 w-4 animate-spin" /> Adding…</> : "Add Connection"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
