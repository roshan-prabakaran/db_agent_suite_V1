"use client";
import { useEffect, useState } from "react";
import { X, Check, Loader2 } from "lucide-react";

interface Employee { id: number; email: string; }
interface Connection { id: number; name: string; }
interface Perm { can_read: boolean; can_write: boolean; can_create_tables: boolean; allowed_tables: string[] | null; }

export default function AccessManagerModal({ onClose }: { onClose: () => void }) {
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [connections, setConnections] = useState<Connection[]>([]);
  const [selectedEmployee, setSelectedEmployee] = useState<number | null>(null);
  const [selectedConn, setSelectedConn] = useState<number | null>(null);
  const [tables, setTables] = useState<string[]>([]);
  const [perms, setPerms] = useState<Perm>({ can_read: false, can_write: false, can_create_tables: false, allowed_tables: null });
  const [existingPerms, setExistingPerms] = useState<Record<number, Perm>>({});
  const [canAddDb, setCanAddDb] = useState(false);
  const [saving, setSaving] = useState(false);
  const [success, setSuccess] = useState("");
  const [loadingTables, setLoadingTables] = useState(false);
  const [loadingPerms, setLoadingPerms] = useState(false);

  // New DB form state
  const [showNewDb, setShowNewDb] = useState(false);
  const [newDb, setNewDb] = useState({ name: "", host: "", port: 5432, database: "", user: "", password: "", can_read: true, can_write: false, can_create_tables: false });
  const [creatingDb, setCreatingDb] = useState(false);

  useEffect(() => {
    fetch("/api/admin/employees").then(r => r.json()).then(d => setEmployees(d.employees || []));
    fetch("/api/admin/connections").then(r => r.json()).then(d => setConnections(d.connections || []));
  }, []);

  // When employee changes, load their existing permissions
  useEffect(() => {
    if (selectedEmployee === null) { setExistingPerms({}); setCanAddDb(false); return; }
    setLoadingPerms(true);
    fetch(`/api/admin/permissions/${selectedEmployee}`)
      .then(r => r.json())
      .then(d => {
        setExistingPerms(d.permissions || {});
        setCanAddDb(d.can_add_db || false);
      })
      .finally(() => setLoadingPerms(false));
  }, [selectedEmployee]);

  // When connection changes, load tables and pre-populate perms from existing
  useEffect(() => {
    if (selectedConn === null) { setTables([]); return; }
    // Pre-populate from existing perms if available
    const existing = existingPerms[selectedConn];
    if (existing) {
      setPerms({ can_read: existing.can_read, can_write: existing.can_write, can_create_tables: existing.can_create_tables, allowed_tables: existing.allowed_tables });
    } else {
      setPerms({ can_read: false, can_write: false, can_create_tables: false, allowed_tables: null });
    }
    setLoadingTables(true);
    fetch(`/api/admin/tables/${selectedConn}`)
      .then(r => r.json())
      .then(d => setTables(d.tables || []))
      .finally(() => setLoadingTables(false));
  }, [selectedConn, existingPerms]);

  const toggleTable = (t: string) => {
    setPerms(p => {
      const current = p.allowed_tables ?? tables; // null means "all" → start with all selected
      const next = current.includes(t) ? current.filter(x => x !== t) : [...current, t];
      return { ...p, allowed_tables: next.length === tables.length ? null : next };
    });
  };

  const handleGlobalSave = async () => {
      if (selectedEmployee === null) return;
      setSaving(true); setSuccess("");
      try {
        const res = await fetch("/api/admin/global-permissions", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ employee_id: selectedEmployee, can_add_db: canAddDb })
        });
        if (res.ok) setSuccess("✅ Global permissions saved!");
        else setSuccess("❌ Failed to save global permissions");
      } catch { setSuccess("❌ Network error"); }
      finally { setSaving(false); }
  };

  const handleSave = async () => {
    if (selectedEmployee === null || selectedConn === null) return;
    setSaving(true); setSuccess("");
    try {
      const res = await fetch("/api/admin/permissions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          connection_id: selectedConn,
          employee_id: selectedEmployee,
          can_read: perms.can_read,
          can_write: perms.can_write,
          can_create_tables: perms.can_create_tables,
          allowed_tables: perms.allowed_tables,
        }),
      });
      if (res.ok) {
        setSuccess("✅ Permissions saved successfully!");
        // Update local cache
        setExistingPerms(prev => ({ ...prev, [selectedConn]: perms }));
      } else {
        const d = await res.json();
        setSuccess("❌ " + (d.detail || "Failed to save"));
      }
    } catch { setSuccess("❌ Network error"); }
    finally { setSaving(false); }
  };

  const handleCreateDb = async () => {
    if (selectedEmployee === null) return;
    setCreatingDb(true); setSuccess("");
    try {
      const res = await fetch("/api/admin/connections", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...newDb, employee_id: selectedEmployee })
      });
      if (res.ok) {
        setSuccess("✅ Database created & assigned to employee!");
        setShowNewDb(false);
        setNewDb({ name: "", host: "", port: 5432, database: "", user: "", password: "", can_read: true, can_write: false, can_create_tables: false });
        
        const d = await fetch("/api/admin/connections").then(r => r.json());
        setConnections(d.connections || []);
        const p = await fetch(`/api/admin/permissions/${selectedEmployee}`).then(r => r.json());
        setExistingPerms(p.permissions || {});
      } else {
        const d = await res.json();
        setSuccess("❌ " + (d.detail || "Failed to create DB"));
      }
    } catch { setSuccess("❌ Network error"); }
    finally { setCreatingDb(false); }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 backdrop-blur-sm p-4">
      <div className="w-full max-w-2xl rounded-2xl bg-white shadow-2xl border border-slate-200 overflow-hidden max-h-[90vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-100 flex-shrink-0">
          <div>
            <h2 className="text-base font-bold text-slate-800">Manage Employee Access</h2>
            <p className="text-xs text-slate-500 mt-0.5">Assign which databases and tables each employee can access</p>
          </div>
          <button onClick={onClose} className="h-7 w-7 rounded-md flex items-center justify-center text-slate-400 hover:bg-slate-100 hover:text-slate-600 transition-colors">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="p-6 space-y-5 overflow-y-auto">
          {/* Step 1: Select Employee */}
          <div>
            <label className="block text-xs font-semibold text-slate-600 mb-1.5">
              1. Select Employee
            </label>
            <select
              className="w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2.5 text-sm text-slate-800 focus:border-violet-400 focus:outline-none focus:ring-2 focus:ring-violet-400/20"
              value={selectedEmployee ?? ""}
              onChange={e => { setSelectedEmployee(e.target.value ? Number(e.target.value) : null); setSelectedConn(null); setSuccess(""); }}
            >
              <option value="">— choose an employee —</option>
              {employees.map(emp => <option key={emp.id} value={emp.id}>{emp.email}</option>)}
            </select>
            {employees.length === 0 && <p className="text-xs text-amber-600 mt-1">No employees found. Register an account to create employee users.</p>}
          </div>

          {/* Step 1.5: Global Permissions */}
          {selectedEmployee !== null && (
            <div className="bg-slate-50 border border-slate-200 rounded-lg p-4">
              <div className="flex items-center justify-between mb-2">
                <label className="text-xs font-semibold text-slate-600">Global Permissions</label>
                <button
                  onClick={handleGlobalSave}
                  disabled={saving}
                  className="text-xs bg-violet-100 hover:bg-violet-200 text-violet-700 px-2 py-1 rounded font-semibold transition-colors disabled:opacity-50"
                >
                  Save Global
                </button>
              </div>
              <label className="flex items-center gap-2 cursor-pointer select-none">
                <div
                  className={`h-4 w-4 rounded flex-shrink-0 flex items-center justify-center border transition-colors ${canAddDb ? "bg-violet-500 border-violet-500" : "border-slate-300 bg-white"}`}
                  onClick={() => setCanAddDb(!canAddDb)}
                >
                  {canAddDb && <Check className="h-2.5 w-2.5 text-white" />}
                </div>
                <span className="text-xs text-slate-700">Allow this employee to add new database connections</span>
              </label>
            </div>
          )}

          {/* Step 2: Select Connection */}
          {selectedEmployee !== null && (
            <div>
              <label className="block text-xs font-semibold text-slate-600 mb-1.5">
                2. Select Database Connection
                {loadingPerms && <span className="ml-2 text-slate-400 font-normal">(loading…)</span>}
              </label>
              <div className="space-y-1.5">
                {connections.map(c => {
                  const ep = existingPerms[c.id];
                  const isActive = selectedConn === c.id;
                  return (
                    <button key={c.id} onClick={() => setSelectedConn(c.id)}
                      className={`w-full flex items-center justify-between px-3 py-2.5 rounded-lg border text-left transition-all ${isActive ? "border-violet-400 bg-violet-50" : "border-slate-200 bg-white hover:bg-slate-50"}`}>
                      <span className={`text-sm font-medium ${isActive ? "text-violet-700" : "text-slate-700"}`}>{c.name}</span>
                      {ep ? (
                        <span className="text-[10px] px-2 py-0.5 rounded-full font-semibold bg-emerald-100 text-emerald-700 flex gap-1">
                          {ep.can_create_tables ? "DDL" : ep.can_write ? "Read & Write" : "Read Only"}
                          {ep.allowed_tables ? ` · ${ep.allowed_tables.length} tables` : ""}
                        </span>
                      ) : (
                        <span className="text-[10px] px-2 py-0.5 rounded-full font-semibold bg-slate-100 text-slate-500">No access</span>
                      )}
                    </button>
                  );
                })}
                {connections.length === 0 && <p className="text-xs text-slate-400 italic">No connections found. Add a database first.</p>}
              </div>
              
              {!showNewDb ? (
                <button
                  onClick={() => { setShowNewDb(true); setSelectedConn(null); }}
                  className="mt-3 w-full border border-dashed border-slate-300 rounded-lg py-2.5 text-xs font-semibold text-violet-600 hover:bg-violet-50 hover:border-violet-300 transition-colors"
                >
                  + Add New DB for this Employee
                </button>
              ) : (
                <div className="mt-3 rounded-xl border border-violet-200 bg-violet-50/50 p-4 space-y-3">
                  <div className="flex items-center justify-between">
                    <h4 className="text-sm font-bold text-violet-900">Add & Assign New Database</h4>
                    <button onClick={() => setShowNewDb(false)} className="text-slate-400 hover:text-slate-600"><X className="h-4 w-4" /></button>
                  </div>
                  <div className="grid grid-cols-2 gap-3">
                    <input type="text" placeholder="Connection Name" className="col-span-2 px-3 py-2 text-sm border border-slate-200 rounded-lg" value={newDb.name} onChange={e => setNewDb(d => ({ ...d, name: e.target.value }))} />
                    <input type="text" placeholder="Host" className="px-3 py-2 text-sm border border-slate-200 rounded-lg" value={newDb.host} onChange={e => setNewDb(d => ({ ...d, host: e.target.value }))} />
                    <input type="number" placeholder="Port" className="px-3 py-2 text-sm border border-slate-200 rounded-lg" value={newDb.port} onChange={e => setNewDb(d => ({ ...d, port: Number(e.target.value) }))} />
                    <input type="text" placeholder="Database Name" className="col-span-2 px-3 py-2 text-sm border border-slate-200 rounded-lg" value={newDb.database} onChange={e => setNewDb(d => ({ ...d, database: e.target.value }))} />
                    <input type="text" placeholder="Username" className="px-3 py-2 text-sm border border-slate-200 rounded-lg" value={newDb.user} onChange={e => setNewDb(d => ({ ...d, user: e.target.value }))} />
                    <input type="password" placeholder="Password" className="px-3 py-2 text-sm border border-slate-200 rounded-lg" value={newDb.password} onChange={e => setNewDb(d => ({ ...d, password: e.target.value }))} />
                  </div>
                  
                  {/* Inline permissions */}
                  <div className="pt-2 border-t border-violet-200/60 grid grid-cols-3 gap-2">
                    <label className="flex items-center gap-1.5 cursor-pointer text-xs font-semibold text-slate-700"><input type="checkbox" checked={newDb.can_read} onChange={e => setNewDb(d => ({ ...d, can_read: e.target.checked }))} /> Read</label>
                    <label className="flex items-center gap-1.5 cursor-pointer text-xs font-semibold text-slate-700"><input type="checkbox" checked={newDb.can_write} onChange={e => setNewDb(d => ({ ...d, can_write: e.target.checked }))} /> Write</label>
                    <label className="flex items-center gap-1.5 cursor-pointer text-xs font-semibold text-slate-700"><input type="checkbox" checked={newDb.can_create_tables} onChange={e => setNewDb(d => ({ ...d, can_create_tables: e.target.checked }))} /> DDL</label>
                  </div>
                  
                  <button onClick={handleCreateDb} disabled={creatingDb || !newDb.name || !newDb.host || !newDb.database} className="w-full mt-2 bg-violet-600 hover:bg-violet-700 text-white rounded-lg py-2 text-sm font-bold shadow-sm disabled:opacity-50 transition-colors flex items-center justify-center gap-2">
                    {creatingDb ? <><Loader2 className="h-4 w-4 animate-spin" /> Saving...</> : "Create & Assign Access"}
                  </button>
                </div>
              )}
            </div>
          )}

          {/* Step 3: Configure permissions */}
          {selectedConn !== null && selectedEmployee !== null && (
            <>
              {/* Permission toggles */}
              <div>
                <label className="block text-xs font-semibold text-slate-600 mb-2">3. Access Level</label>
                <div className="grid grid-cols-2 gap-3 mb-3">
                  {[
                    { label: "Read (SELECT)", key: "can_read" },
                    { label: "Write (INSERT / UPDATE / DELETE)", key: "can_write" },
                    { label: "Create/Modify Tables (DDL)", key: "can_create_tables" }
                  ].map(({ label, key }) => (
                    <label key={key} className="flex items-center gap-2 cursor-pointer select-none bg-slate-50 border border-slate-200 rounded-lg px-3 py-2 flex-1">
                      <div
                        className={`h-5 w-5 rounded flex-shrink-0 flex items-center justify-center border transition-colors ${(perms as any)[key] ? "bg-violet-500 border-violet-500" : "border-slate-300 bg-white"}`}
                        onClick={() => setPerms(p => {
                          const next = { ...p, [key]: !(p as any)[key] };
                          if (key === "can_write" && next.can_write) next.can_read = true;
                          if (key === "can_create_tables" && next.can_create_tables) {
                              next.can_write = true;
                              next.can_read = true;
                          }
                          if (key === "can_read" && !next.can_read) {
                              next.can_write = false;
                              next.can_create_tables = false;
                          }
                          return next;
                        })}
                      >
                        {(perms as any)[key] && <Check className="h-3 w-3 text-white" />}
                      </div>
                      <span className="text-xs text-slate-700">{label}</span>
                    </label>
                  ))}
                </div>
              </div>

              {/* Table access */}
              <div>
                <div className="flex items-center justify-between mb-2">
                  <label className="text-xs font-semibold text-slate-600">4. Table Restrictions (optional)</label>
                  <div className="flex gap-2">
                    <button onClick={() => setPerms(p => ({ ...p, allowed_tables: null }))} className="text-xs text-violet-600 hover:underline">All tables</button>
                    <span className="text-slate-300">|</span>
                    <button onClick={() => setPerms(p => ({ ...p, allowed_tables: [] }))} className="text-xs text-slate-500 hover:underline">None</button>
                  </div>
                </div>
                {loadingTables ? (
                  <div className="flex items-center gap-2 text-slate-400 text-xs py-3">
                    <Loader2 className="h-3 w-3 animate-spin" /> Loading tables…
                  </div>
                ) : tables.length === 0 ? (
                  <p className="text-xs text-slate-400 italic">No public tables found in this database.</p>
                ) : (
                  <>
                    <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 grid grid-cols-3 gap-1.5 max-h-44 overflow-y-auto">
                      {tables.map(t => {
                        const checked = perms.allowed_tables === null || perms.allowed_tables.includes(t);
                        return (
                          <label key={t} className="flex items-center gap-1.5 cursor-pointer">
                            <div
                              className={`h-4 w-4 rounded flex-shrink-0 flex items-center justify-center border transition-colors ${checked ? "bg-violet-500 border-violet-500" : "border-slate-300 bg-white"}`}
                              onClick={() => toggleTable(t)}
                            >
                              {checked && <Check className="h-2.5 w-2.5 text-white" />}
                            </div>
                            <span className="text-xs text-slate-700 truncate font-mono">{t}</span>
                          </label>
                        );
                      })}
                    </div>
                    {perms.allowed_tables !== null && (
                      <p className="text-xs text-amber-600 mt-1.5">
                        ⚠ Restricted to {perms.allowed_tables.length} table(s). Click "All tables" to remove restriction.
                      </p>
                    )}
                  </>
                )}
              </div>
            </>
          )}

          {success && (
            <p className={`text-sm font-medium ${success.startsWith("✅") ? "text-emerald-600" : "text-rose-600"}`}>{success}</p>
          )}
        </div>

        {/* Footer */}
        <div className="flex gap-3 px-6 py-4 border-t border-slate-100 flex-shrink-0">
          <button onClick={onClose} className="flex-1 rounded-lg border border-slate-200 py-2.5 text-sm font-medium text-slate-600 hover:bg-slate-50 transition-colors">
            Close
          </button>
          <button
            onClick={handleSave}
            disabled={saving || selectedEmployee === null || selectedConn === null}
            className="flex-1 rounded-lg bg-violet-500 hover:bg-violet-600 py-2.5 text-sm font-semibold text-white transition-colors shadow-sm disabled:opacity-40 flex items-center justify-center gap-2"
          >
            {saving ? <><Loader2 className="h-4 w-4 animate-spin" /> Saving…</> : "Save Permissions"}
          </button>
        </div>
      </div>
    </div>
  );
}
