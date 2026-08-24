"use client";
import { Chart as ChartJS, CategoryScale, LinearScale, PointElement, LineElement, BarElement, ArcElement, Title, Tooltip, Legend } from "chart.js";
import { Bar, Line, Pie, Scatter } from "react-chartjs-2";
import { useState } from "react";
import { Pin } from "lucide-react";

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, BarElement, ArcElement, Title, Tooltip, Legend);

export default function ChartRenderer({ specJson, sessionId, connectionId, hidePin = false }: { specJson: string, sessionId?: string, connectionId?: number, hidePin?: boolean }) {
  const [pinned, setPinned] = useState(false);
  let spec;
  try { spec = JSON.parse(specJson); } catch { return <p className="text-red-500 text-xs">Invalid chart JSON</p>; }

  const options = { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: "bottom" as const }, title: { display: !!spec.title, text: spec.title || "" } } };
  
  // Assign colours if missing
  const colors = ["#8b5cf6", "#ec4899", "#14b8a6", "#f59e0b", "#3b82f6"];
  if (spec.datasets) {
    spec.datasets.forEach((ds: any, i: number) => {
      if (!ds.backgroundColor) {
        ds.backgroundColor = spec.type === "pie" ? colors : colors[i % colors.length] + "80";
        ds.borderColor = spec.type === "pie" ? "#fff" : colors[i % colors.length];
        ds.borderWidth = 2;
      }
    });
  }

  const handlePin = async () => {
    if (!sessionId || !connectionId || pinned) return;
    try {
      await fetch("/api/dashboard/pins", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, connection_id: connectionId, chart_json: specJson, title: spec.title || "Untitled Chart" })
      });
      setPinned(true);
    } catch (e) { console.error("Failed to pin chart"); }
  };

  return (
    <div className="relative border border-slate-200 rounded-xl p-4 bg-white shadow-sm my-4">
      {!hidePin && (
        <button onClick={handlePin} disabled={pinned} className={`absolute top-2 right-2 p-1.5 rounded-md text-xs font-semibold flex items-center gap-1 transition-colors ${pinned ? "bg-emerald-100 text-emerald-700" : "bg-slate-100 text-slate-600 hover:bg-slate-200"}`}>
          <Pin className="h-3 w-3" /> {pinned ? "Pinned!" : "Pin to Dashboard"}
        </button>
      )}
      <div className="h-64 w-full mt-2">
        {spec.type === "bar" && <Bar data={spec} options={options} />}
        {spec.type === "line" && <Line data={spec} options={options} />}
        {spec.type === "pie" && <Pie data={spec} options={options} />}
        {spec.type === "scatter" && <Scatter data={spec} options={options} />}
      </div>
    </div>
  );
}
