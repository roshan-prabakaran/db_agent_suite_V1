"use client";
import { useEffect, useState } from "react";
import { MessageSquare, Trash2 } from "lucide-react";

interface Session { id: string; title: string; }

interface ChatHistorySidebarProps {
  onSelectSession: (sessionId: string) => void;
  onDeleteSession: (sessionId: string) => void;
  activeSessionId: string | null;
}

export default function ChatHistorySidebar({ onSelectSession, onDeleteSession, activeSessionId }: ChatHistorySidebarProps) {
  const [sessions, setSessions] = useState<Session[]>([]);

  const fetchSessions = async () => {
    try {
      const res = await fetch("/api/chat/sessions");
      if (res.ok) { const data = await res.json(); setSessions(data.sessions || []); }
    } catch (e) { console.error("Failed to load chat history", e); }
  };

  useEffect(() => { fetchSessions(); }, [activeSessionId]);

  const handleDelete = async (e: React.MouseEvent, sessionId: string) => {
    e.stopPropagation();
    if (!confirm("Delete this chat session?")) return;
    try {
      const res = await fetch(`/api/chat/sessions/${sessionId}`, { method: "DELETE" });
      if (res.ok) { setSessions(s => s.filter(x => x.id !== sessionId)); onDeleteSession(sessionId); }
    } catch (err) { console.error("Failed to delete", err); }
  };

  if (sessions.length === 0) return null;

  return (
    <div className="mt-4 pt-4 border-t border-slate-100">
      <h2 className="text-[10px] font-bold uppercase tracking-widest text-slate-400 mb-2 px-1">Chat History</h2>
      <div className="space-y-0.5">
        {sessions.map((session) => (
          <div key={session.id} className={`flex items-center group rounded-md transition-colors ${
            activeSessionId === session.id
              ? "bg-violet-50 text-violet-700"
              : "text-slate-600 hover:bg-slate-50"
          }`}>
            <button onClick={() => onSelectSession(session.id)} className="flex-1 flex items-center gap-2 px-3 py-2 text-left min-w-0" title={session.title}>
              <MessageSquare className="h-3 w-3 flex-shrink-0 opacity-60" />
              <span className="text-xs truncate">{session.title}</span>
            </button>
            <button onClick={(e) => handleDelete(e, session.id)} className="px-1.5 py-2 opacity-0 group-hover:opacity-100 text-slate-300 hover:text-rose-500 transition-all flex-shrink-0" title="Delete session">
              <Trash2 className="h-3 w-3" />
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
