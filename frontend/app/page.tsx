"use client";
import { useAuth } from "@/components/AuthProvider";
import { useTheme } from "@/components/ThemeProvider";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useEffect, useState, useRef } from "react";
import { v4 as uuidv4 } from "uuid";
import Link from "next/link";
import AddConnectionModal from "@/components/AddConnectionModal";
import AccessManagerModal from "@/components/AccessManagerModal";
import SessionsModal from "@/components/SessionsModal";
import ChatHistorySidebar from "@/components/ChatHistorySidebar";
import ChartRenderer from "@/components/ChartRenderer";
import { Database, Plus, Settings, LogOut, Send, Bot, User, Loader2, Trash2, MessageSquarePlus, LayoutDashboard, CheckCircle, XCircle, AlertTriangle, Shield } from "lucide-react";

interface Connection { id: number; name: string; }
interface Message { role: string; content: string; pending_sql?: string; }

export default function Home() {
  const { user, loading, logout } = useAuth();
  const { theme, toggleTheme } = useTheme();
  const [connections, setConnections] = useState<Connection[]>([]);
  const [activeConnectionId, setActiveConnectionId] = useState<number | null>(null);
  const [sessionId, setSessionId] = useState<string>("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [isProcessing, setIsProcessing] = useState(false);
  const [showAddConn, setShowAddConn] = useState(false);
  const [showAccessMgr, setShowAccessMgr] = useState(false);
  const [showSessionsMgr, setShowSessionsMgr] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!sessionId) {
      const stored = sessionStorage.getItem("activeSessionId");
      if (stored) { setSessionId(stored); }
      else { const newId = uuidv4().substring(0, 8); setSessionId(newId); sessionStorage.setItem("activeSessionId", newId); }
    } else { sessionStorage.setItem("activeSessionId", sessionId); }
  }, [sessionId]);

  const loadConnections = () => {
    fetch("/api/connections").then(r => r.json()).then(d => { if (d.connections) setConnections(d.connections); }).catch(console.error);
  };

  useEffect(() => { if (user) loadConnections(); }, [user]);

  useEffect(() => {
    if (sessionId && user) {
      fetch(`/api/chat/history/${sessionId}`).then(r => r.json()).then(d => {
        if (d.history) {
          setMessages(d.history
            .filter((m: any) => !m.content.startsWith("[SYSTEM_HIDDEN]"))
            .map((m: any) => ({ role: m.role === "human" || m.role === "user" ? "user" : "assistant", content: m.content })));
        }
      });
    }
  }, [sessionId, user]);

  useEffect(() => { messagesEndRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages]);

  const handleNewSession = () => {
    const newId = uuidv4().substring(0, 8);
    setSessionId(newId); setMessages([]); sessionStorage.setItem("activeSessionId", newId);
  };

  const handleAutoSwitchMessage = async (newConnId: number, newConnName: string) => {
    const sysMsg = `[SYSTEM_HIDDEN] The user has switched the active database connection to "${newConnName}". Please briefly analyze its tables and schema, and acknowledge the switch.`;
    setIsProcessing(true);
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 300_000); // 5 min timeout
    try {
      const res = await fetch("/api/chat/message", { 
        method: "POST", headers: { "Content-Type": "application/json" }, 
        body: JSON.stringify({ message: sysMsg, session_id: sessionId, connection_id: newConnId }),
        signal: controller.signal,
      });
      const data = await res.json();
      if (res.ok && data.status === "success") { setMessages(prev => [...prev, ...data.new_messages]); }
      else if (res.ok && data.status === "pending_approval") {
        setMessages(prev => [...prev, { role: "assistant", content: "⚠️ Approval required before executing:", pending_sql: data.pending_sql }]);
      }
      else { setMessages(prev => [...prev, { role: "assistant", content: "⚠️ " + (data.message || "Unknown error occurred.") }]); }
    } catch (err: unknown) {
      const msg = (err instanceof Error && err.name === "AbortError")
        ? "The request took too long and was cancelled. The agent may still be processing — please try again."
        : "Lost connection to the server. Please check if the API is running.";
      setMessages(prev => [...prev, { role: "assistant", content: "⚠️ " + msg }]);
    } finally {
      clearTimeout(timeout);
      setIsProcessing(false);
      setTimeout(() => messagesEndRef.current?.scrollIntoView({ behavior: "smooth" }), 100);
    }
  };

  const handleSendMessage = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || isProcessing || activeConnectionId === null) return;
    const userMessage = input.trim();
    setInput(""); setMessages(prev => [...prev, { role: "user", content: userMessage }]); setIsProcessing(true);
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 300_000); // 5 min timeout
    try {
      const res = await fetch("/api/chat/message", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: userMessage, session_id: sessionId, connection_id: activeConnectionId }),
        signal: controller.signal,
      });
      const data = await res.json();
      if (res.ok && data.status === "success") { 
        setMessages(prev => [...prev, ...data.new_messages]); 
        if (data.switched_connection_id && data.switched_connection_id !== activeConnectionId) {
          if (!connections.find(c => c.id === data.switched_connection_id)) {
            loadConnections();
          }
          setActiveConnectionId(data.switched_connection_id);
        }
      }
      else if (res.ok && data.status === "pending_approval") {
        setMessages(prev => [...prev, { role: "assistant", content: "⚠️ Approval required before executing:", pending_sql: data.pending_sql }]);
      }
      else { setMessages(prev => [...prev, { role: "assistant", content: "⚠️ " + (data.message || "Unknown error occurred.") }]); }
    } catch (err: unknown) {
      const msg = (err instanceof Error && err.name === "AbortError")
        ? "The request took too long and was cancelled. The agent may still be processing — please try again."
        : "Lost connection to the server. Please check if the API is running.";
      setMessages(prev => [...prev, { role: "assistant", content: "⚠️ " + msg }]);
    } finally {
      clearTimeout(timeout);
      setIsProcessing(false);
      setTimeout(() => inputRef.current?.focus(), 100);
    }
  };

  const handleApproval = async (approved: boolean) => {
    setIsProcessing(true);
    // Remove the pending message

    setMessages(prev => prev.filter(m => !m.pending_sql));
    try {
      const res = await fetch("/api/chat/approve", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, approved, connection_id: activeConnectionId })
      });
      const data = await res.json();
      if (approved) {
        setMessages(prev => [...prev, { role: "assistant", content: "✅ Approved! Executing..." }]);
      } else {
        setMessages(prev => [...prev, { role: "assistant", content: "❌ Operation cancelled." }]);
      }
      if (data.status === "success" && data.new_messages?.length) {
        setMessages(prev => [...prev.filter(m => m.content !== "✅ Approved! Executing..."), ...data.new_messages]);
      } else if (data.status === "pending_approval") {
        setMessages(prev => [...prev, { role: "assistant", content: "⚠️ Another approval required:", pending_sql: data.pending_sql }]);
      }
    } catch { setMessages(prev => [...prev, { role: "assistant", content: "❌ Network error during approval." }]); }
    finally { setIsProcessing(false); }
  };

  const activeConnection = connections.find(c => c.id === activeConnectionId);

  if (loading || !user) return (
    <div className="flex h-screen items-center justify-center bg-slate-50">
      <div className="flex flex-col items-center gap-3">
        <Loader2 className="h-8 w-8 animate-spin text-violet-500" />
        <p className="text-sm text-slate-500">Loading...</p>
      </div>
    </div>
  );

  return (
    <div className="flex h-screen bg-slate-100 dark:bg-slate-950 overflow-hidden transition-colors duration-200">
      {/* Sidebar */}
      <aside className="w-64 flex-shrink-0 flex flex-col bg-white dark:bg-slate-900 border-r border-slate-200 dark:border-slate-800 transition-colors duration-200">
        <div className="px-5 py-4 border-b border-slate-100 dark:border-slate-800">
          <div className="flex items-center gap-2">
            <div className="h-8 w-8 rounded-lg bg-violet-500 flex items-center justify-center">
              <Database className="h-4 w-4 text-white" />
            </div>
            <span className="font-bold text-slate-800 dark:text-slate-100 tracking-tight">DB Agent</span>
          </div>
        </div>

        <div className="px-4 pt-4 pb-2">
          <div className="flex items-center justify-between mb-2">
            <span className="text-[10px] font-bold uppercase tracking-widest text-slate-400 dark:text-slate-500">Databases</span>
            {(user.role === "admin" || user.can_add_db) && (
              <button onClick={() => setShowAddConn(true)} className="h-6 w-6 rounded-md flex items-center justify-center bg-violet-50 dark:bg-violet-900/30 hover:bg-violet-100 dark:hover:bg-violet-900/50 text-violet-600 dark:text-violet-400 transition-colors" title="Add Connection">
                <Plus className="h-3.5 w-3.5" />
              </button>
            )}
          </div>

          <div className="space-y-0.5 max-h-48 overflow-y-auto">
            {connections.length === 0 ? (
              <p className="text-xs text-slate-400 dark:text-slate-600 italic px-2 py-2">No databases added yet.</p>
            ) : connections.map(conn => (
              <div key={conn.id} className="group flex items-center">
                <button 
                  onClick={() => {
                    if (isProcessing) return;
                    if (activeConnectionId !== conn.id) {
                      setActiveConnectionId(conn.id);
                      if (messages.length > 0) {
                        handleAutoSwitchMessage(conn.id, conn.name);
                      }
                    }
                  }} 
                  className={`flex-1 flex items-center gap-2 px-3 py-2 text-sm rounded-md transition-all text-left ${activeConnectionId === conn.id ? "bg-violet-50 dark:bg-violet-900/20 text-violet-700 dark:text-violet-400 font-semibold" : "text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-800"}`}
                >
                  <Database className="h-3.5 w-3.5 flex-shrink-0 opacity-60" />
                  <span className="truncate">{conn.name}</span>
                </button>
                <button onClick={async (e) => { e.stopPropagation(); if (!confirm("Delete this database connection?")) return; await fetch(`/api/connections/${conn.id}`, { method: "DELETE" }); loadConnections(); if (activeConnectionId === conn.id) setActiveConnectionId(null); }} className="px-1.5 py-2 opacity-0 group-hover:opacity-100 text-slate-300 dark:text-slate-600 hover:text-rose-500 dark:hover:text-rose-400 transition-all" title="Delete">
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            ))}
          </div>
        </div>

        <div className="flex-1 overflow-y-auto px-4 pb-2">
          <ChatHistorySidebar activeSessionId={sessionId} onSelectSession={id => { setSessionId(id); setMessages([]); }} onDeleteSession={id => { if (id === sessionId) handleNewSession(); }} />
        </div>

        <div className="px-4 pb-4 pt-2 border-t border-slate-100 dark:border-slate-800 space-y-1.5">
          <Link href="/dashboard" className="w-full flex items-center justify-center gap-2 rounded-lg bg-amber-50 dark:bg-amber-900/20 hover:bg-amber-100 dark:hover:bg-amber-900/40 py-2.5 text-sm font-semibold text-amber-700 dark:text-amber-500 transition-colors">
            <LayoutDashboard className="h-4 w-4" /> Visual Dashboard
          </Link>
          <button onClick={handleNewSession} className="w-full flex items-center justify-center gap-2 rounded-lg bg-violet-500 hover:bg-violet-600 py-2.5 text-sm font-semibold text-white transition-colors shadow-sm">
            <MessageSquarePlus className="h-4 w-4" /> New Chat
          </button>
          {user.role === "admin" && (
            <button onClick={() => setShowAccessMgr(true)} className="w-full flex items-center justify-center gap-2 rounded-lg bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700 py-2 text-xs font-semibold text-slate-600 dark:text-slate-300 transition-colors">
              <Settings className="h-3.5 w-3.5" /> Manage Access
            </button>
          )}
          <button onClick={() => setShowSessionsMgr(true)} className="w-full flex items-center justify-center gap-2 rounded-lg bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700 py-2 text-xs font-semibold text-slate-600 dark:text-slate-300 transition-colors">
            <Shield className="h-3.5 w-3.5" /> Active Sessions
          </button>
        </div>

        <div className="px-4 py-3 border-t border-slate-100 dark:border-slate-800 bg-slate-50 dark:bg-slate-900/50 flex items-center justify-between">
          <div className="min-w-0">
            <p className="text-xs font-semibold text-slate-700 dark:text-slate-300 truncate">{user.email}</p>
            <p className="text-[10px] text-slate-400 dark:text-slate-500 capitalize">{user.role}</p>
          </div>
          <div className="flex items-center gap-1">
            <button onClick={toggleTheme} className="h-7 w-7 rounded-md flex items-center justify-center text-slate-400 dark:text-slate-500 hover:bg-slate-200 dark:hover:bg-slate-800 hover:text-slate-600 dark:hover:text-slate-300 transition-colors" title={theme === "light" ? "Switch to Dark Mode" : "Switch to Light Mode"}>
              {theme === "light" ? <span className="text-sm">🌙</span> : <span className="text-sm">☀️</span>}
            </button>
            <button onClick={logout} className="h-7 w-7 rounded-md flex items-center justify-center text-slate-400 dark:text-slate-500 hover:bg-rose-50 dark:hover:bg-rose-900/20 hover:text-rose-500 dark:hover:text-rose-400 transition-colors" title="Sign Out">
              <LogOut className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
      </aside>

      {/* Chat Area */}
      <main className="flex flex-1 flex-col overflow-hidden bg-slate-100 dark:bg-slate-950">
        <header className="flex h-14 flex-shrink-0 items-center justify-between border-b border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 px-6 transition-colors duration-200">
          <div className="flex items-center gap-2">
            <div className={`h-2 w-2 rounded-full ${activeConnection ? "bg-emerald-400" : "bg-slate-300 dark:bg-slate-600"}`} />
            <span className={`text-sm font-semibold ${activeConnection ? "text-slate-700 dark:text-slate-200" : "text-slate-400 dark:text-slate-500"}`}>
              {activeConnection ? activeConnection.name : "No database selected"}
            </span>
          </div>
          <span className="text-xs text-slate-400 dark:text-slate-500 bg-slate-100 dark:bg-slate-800 px-2 py-0.5 rounded font-mono">session: {sessionId}</span>
        </header>

        <div className="flex-1 overflow-y-auto px-6 py-6 space-y-5">
          {messages.length === 0 ? (
            <div className="flex h-full flex-col items-center justify-center gap-4 text-slate-400 dark:text-slate-500 select-none">
              <div className="h-16 w-16 rounded-2xl bg-violet-50 dark:bg-violet-900/20 border border-violet-100 dark:border-violet-800/30 flex items-center justify-center">
                <Bot className="h-8 w-8 text-violet-400 dark:text-violet-500" />
              </div>
              <div className="text-center">
                <p className="font-semibold text-slate-600 dark:text-slate-300">Ask anything about your database</p>
                <p className="text-sm mt-1">{activeConnectionId ? "Type your question below to get started." : "Select a database from the sidebar first."}</p>
              </div>
              {!activeConnectionId && (
                (user.role === "admin" || user.can_add_db) ? (
                  <button onClick={() => setShowAddConn(true)} className="flex items-center gap-2 rounded-lg border border-dashed border-violet-300 dark:border-violet-700/50 px-4 py-2 text-sm text-violet-500 dark:text-violet-400 hover:bg-violet-50 dark:hover:bg-violet-900/20 transition-colors">
                    <Plus className="h-4 w-4" /> Add a database connection
                  </button>
                ) : (
                  <p className="text-xs text-slate-400 dark:text-slate-500 italic">Contact your admin to get database access.</p>
                )
              )}


            </div>
          ) : messages.map((msg, idx) => (
            <div key={idx} className={`flex items-start gap-3 ${msg.role === "user" ? "flex-row-reverse" : ""}`}>
              <div className={`h-8 w-8 rounded-full flex-shrink-0 flex items-center justify-center text-white ${msg.role === "user" ? "bg-violet-500" : "bg-slate-700 dark:bg-slate-600"}`}>
                {msg.role === "user" ? <User className="h-4 w-4" /> : <Bot className="h-4 w-4" />}
              </div>
              <div className={`max-w-3xl rounded-2xl px-5 py-3.5 overflow-x-auto min-w-0 ${msg.role === "user" ? "bg-violet-500 text-white rounded-tr-sm" : "bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 text-slate-800 dark:text-slate-200 rounded-tl-sm shadow-sm"}`}>
                {msg.role === "user" ? (
                  <p className="text-sm whitespace-pre-wrap">{msg.content}</p>
                ) : msg.pending_sql ? (
                  /* Approval Card */
                  <div className="space-y-3">
                    <div className="flex items-center gap-2 text-amber-600 dark:text-amber-500">
                      <AlertTriangle className="h-4 w-4 flex-shrink-0" />
                      <span className="text-sm font-semibold">Confirmation Required</span>
                    </div>
                    <p className="text-xs text-slate-500 dark:text-slate-400">{msg.content.replace("⚠️ Approval required before executing:", "").trim()}</p>
                    <pre className="bg-slate-900 dark:bg-black/50 text-emerald-300 dark:text-emerald-400 rounded-lg p-3 text-xs font-mono overflow-x-auto whitespace-pre-wrap">{msg.pending_sql}</pre>
                    <div className="flex gap-2 pt-1">
                      <button onClick={() => handleApproval(true)} disabled={isProcessing} className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-emerald-500 hover:bg-emerald-600 text-white text-sm font-semibold transition-colors disabled:opacity-50 shadow-sm">
                        <CheckCircle className="h-4 w-4" /> Confirm
                      </button>
                      <button onClick={() => handleApproval(false)} disabled={isProcessing} className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-rose-100 dark:bg-rose-900/30 hover:bg-rose-200 dark:hover:bg-rose-900/50 text-rose-700 dark:text-rose-400 text-sm font-semibold transition-colors disabled:opacity-50">
                        <XCircle className="h-4 w-4" /> Cancel
                      </button>
                    </div>
                  </div>
                ) : (
                  <div className="text-sm leading-relaxed">
                    <ReactMarkdown remarkPlugins={[remarkGfm]} components={{
                      table: ({ node, ...props }) => <div className="overflow-x-auto my-3 rounded-lg border border-slate-200 dark:border-slate-700"><table className="min-w-full divide-y divide-slate-200 dark:divide-slate-700" {...props} /></div>,
                      thead: ({ node, ...props }) => <thead className="bg-slate-50 dark:bg-slate-800/50" {...props} />,
                      th: ({ node, ...props }) => <th className="px-4 py-2.5 text-left text-xs font-bold text-slate-600 dark:text-slate-300 uppercase tracking-wider whitespace-nowrap" {...props} />,
                      td: ({ node, ...props }) => <td className="px-4 py-2.5 text-sm text-slate-700 dark:text-slate-300 border-t border-slate-100 dark:border-slate-800 whitespace-nowrap" {...props} />,
                      tr: ({ node, ...props }) => <tr className="even:bg-slate-50/50 dark:even:bg-slate-800/20 hover:bg-violet-50/30 dark:hover:bg-violet-900/10 transition-colors" {...props} />,
                      code: ({ node, className, children, ...props }: any) => {
                        const isChart = className === "language-chart";
                        if (isChart) return <ChartRenderer specJson={String(children)} sessionId={sessionId} connectionId={activeConnectionId!} />;
                        return !className
                          ? <code className="bg-slate-100 dark:bg-slate-800 text-violet-700 dark:text-violet-400 px-1.5 py-0.5 rounded text-xs font-mono" {...props}>{children}</code>
                          : <pre className="bg-slate-900 text-slate-100 rounded-lg p-4 overflow-x-auto my-3 text-xs font-mono"><code>{children}</code></pre>;
                      },
                      p: ({ node, ...props }) => <p className="mb-2 last:mb-0" {...props} />,
                      ul: ({ node, ...props }) => <ul className="list-disc list-inside mb-2 space-y-1" {...props} />,
                      ol: ({ node, ...props }) => <ol className="list-decimal list-inside mb-2 space-y-1" {...props} />,
                      strong: ({ node, ...props }) => <strong className="font-semibold text-slate-900 dark:text-slate-100" {...props} />,
                    }}>
                      {msg.content}
                    </ReactMarkdown>
                  </div>
                )}
              </div>
            </div>
          ))}

          {isProcessing && (
            <div className="flex items-start gap-3">
              <div className="h-8 w-8 rounded-full bg-slate-700 dark:bg-slate-600 flex items-center justify-center flex-shrink-0">
                <Bot className="h-4 w-4 text-white" />
              </div>
              <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl rounded-tl-sm px-5 py-3.5 shadow-sm">
                <div className="flex items-center gap-1.5">
                  <div className="h-2 w-2 bg-violet-400 rounded-full animate-bounce [animation-delay:-0.3s]" />
                  <div className="h-2 w-2 bg-violet-400 rounded-full animate-bounce [animation-delay:-0.15s]" />
                  <div className="h-2 w-2 bg-violet-400 rounded-full animate-bounce" />
                </div>
              </div>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>

        <div className="flex-shrink-0 border-t border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 px-6 py-4 transition-colors duration-200">
          <form onSubmit={handleSendMessage} className="flex items-center gap-3 max-w-4xl mx-auto">
            <input ref={inputRef} type="text" value={input} onChange={e => setInput(e.target.value)}
              placeholder={activeConnectionId ? "Ask a question about your database…" : "Select a database connection to start chatting"}
              disabled={isProcessing || activeConnectionId === null}
              className="flex-1 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 px-4 py-3 text-sm text-slate-800 dark:text-slate-100 placeholder-slate-400 dark:placeholder-slate-500 focus:border-violet-400 dark:focus:border-violet-500 focus:bg-white dark:focus:bg-slate-900 focus:outline-none focus:ring-2 focus:ring-violet-400/20 dark:focus:ring-violet-500/20 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
            />
            <button type="submit" disabled={isProcessing || !input.trim() || activeConnectionId === null}
              className="h-11 w-11 rounded-xl bg-violet-500 hover:bg-violet-600 flex items-center justify-center text-white shadow-md shadow-violet-200 transition-all disabled:opacity-40 disabled:cursor-not-allowed flex-shrink-0">
              {isProcessing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
            </button>
          </form>
        </div>
      </main>

      {showAddConn && <AddConnectionModal onClose={() => setShowAddConn(false)} onAdded={loadConnections} />}
      {showAccessMgr && <AccessManagerModal onClose={() => setShowAccessMgr(false)} />}
      {showSessionsMgr && <SessionsModal onClose={() => setShowSessionsMgr(false)} />}
    </div>
  );
}
