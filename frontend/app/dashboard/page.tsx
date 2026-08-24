"use client";
import { useEffect, useState } from "react";
import { useAuth } from "@/components/AuthProvider";
import { ArrowLeft, Trash2, LayoutDashboard, Loader2, Database } from "lucide-react";
import Link from "next/link";
import ChartRenderer from "@/components/ChartRenderer";

interface Connection { id: number; name: string; }

export default function Dashboard() {
  const { user, loading } = useAuth();
  const [pins, setPins] = useState<any[]>([]);
  const [connections, setConnections] = useState<Connection[]>([]);
  const [filterConnId, setFilterConnId] = useState<number | "all">("all");
  const [fetching, setFetching] = useState(true);

  useEffect(() => {
    if (user) {
      Promise.all([
        fetch("/api/dashboard/pins").then(r => r.json()),
        fetch("/api/connections").then(r => r.json())
      ]).then(([pinsData, connsData]) => {
        setPins(pinsData.pins || []);
        setConnections(connsData.connections || []);
      }).finally(() => setFetching(false));
    }
  }, [user]);

  const deletePin = async (id: number) => {
    if (!confirm("Remove this chart from the dashboard?")) return;
    try {
      await fetch(`/api/dashboard/pins/${id}`, { method: "DELETE" });
      setPins(p => p.filter(x => x.id !== id));
    } catch {}
  };

  if (loading || fetching) return <div className="flex h-screen items-center justify-center bg-slate-50 dark:bg-slate-950"><Loader2 className="animate-spin text-violet-500" /></div>;
  if (!user) return <p>Unauthorized</p>;

  const filteredPins = filterConnId === "all" ? pins : pins.filter(p => p.connection_id === filterConnId);

  return (
    <div className="min-h-screen bg-slate-50 dark:bg-slate-950 transition-colors duration-200">
      <header className="bg-white dark:bg-slate-900 border-b border-slate-200 dark:border-slate-800 px-6 py-4 flex items-center justify-between sticky top-0 z-10 shadow-sm transition-colors duration-200">
        <div className="flex items-center gap-4">
          <Link href="/" className="h-8 w-8 rounded-md bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700 flex items-center justify-center text-slate-600 dark:text-slate-300 transition-colors">
            <ArrowLeft className="h-4 w-4" />
          </Link>
          <div className="flex items-center gap-2">
            <LayoutDashboard className="h-5 w-5 text-violet-500" />
            <h1 className="text-lg font-bold text-slate-800 dark:text-slate-100">Visual Dashboard</h1>
          </div>
        </div>
        
        {/* DB Filter */}
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2 bg-slate-100 dark:bg-slate-800 px-3 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700">
            <Database className="h-3.5 w-3.5 text-slate-400 dark:text-slate-500" />
            <select 
              className="bg-transparent text-sm font-medium text-slate-700 dark:text-slate-300 focus:outline-none cursor-pointer appearance-none pr-4"
              value={filterConnId} 
              onChange={e => setFilterConnId(e.target.value === "all" ? "all" : Number(e.target.value))}
            >
              <option value="all">All Databases</option>
              {connections.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </div>
          <span className="text-sm font-medium text-slate-500 hidden sm:block border-l border-slate-300 dark:border-slate-700 pl-3">{user.email}</span>
        </div>
      </header>

      <main className="p-8 max-w-7xl mx-auto">
        {filteredPins.length === 0 ? (
          <div className="text-center py-20 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl shadow-sm transition-colors duration-200">
            <div className="h-16 w-16 bg-slate-100 dark:bg-slate-800 rounded-full flex items-center justify-center mx-auto mb-4">
              <LayoutDashboard className="h-8 w-8 text-slate-400 dark:text-slate-500" />
            </div>
            <h2 className="text-xl font-bold text-slate-700 dark:text-slate-200 mb-2">
              {filterConnId === "all" ? "No pinned charts" : "No charts for this database"}
            </h2>
            <p className="text-slate-500 dark:text-slate-400">Ask the DB Agent to generate charts and pin them to build your dashboard.</p>
            <Link href="/" className="mt-6 inline-flex text-sm font-semibold text-violet-600 dark:text-violet-400 hover:text-violet-700 dark:hover:text-violet-300 bg-violet-50 dark:bg-violet-900/30 hover:bg-violet-100 dark:hover:bg-violet-900/50 px-4 py-2 rounded-lg transition-colors">
              Go to Chat
            </Link>
          </div>
        ) : (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {filteredPins.map(p => {
              const connName = connections.find(c => c.id === p.connection_id)?.name || "Unknown Database";
              return (
                <div key={p.id} className="relative group bg-white dark:bg-slate-900 p-2 rounded-2xl shadow-sm border border-slate-200 dark:border-slate-800 transition-colors duration-200 flex flex-col">
                  <div className="absolute top-4 left-4 z-10 flex items-center gap-1.5 px-2 py-1 rounded-md bg-slate-100/80 dark:bg-slate-800/80 backdrop-blur border border-slate-200 dark:border-slate-700 text-[10px] font-semibold text-slate-600 dark:text-slate-300 shadow-sm pointer-events-none">
                    <Database className="h-3 w-3 opacity-70" /> {connName}
                  </div>
                  <button onClick={() => deletePin(p.id)} className="absolute top-4 right-4 p-2 rounded-lg bg-white/90 dark:bg-slate-800/90 backdrop-blur text-slate-400 dark:text-slate-500 opacity-0 group-hover:opacity-100 hover:text-rose-500 dark:hover:text-rose-400 hover:bg-rose-50 dark:hover:bg-rose-900/20 transition-all z-10 shadow-sm border border-slate-100 dark:border-slate-700">
                    <Trash2 className="h-4 w-4" />
                  </button>
                  <ChartRenderer specJson={p.chart_json} hidePin={true} />
                </div>
              );
            })}
          </div>
        )}
      </main>
    </div>
  );
}
