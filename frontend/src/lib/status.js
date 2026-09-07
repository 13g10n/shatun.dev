export function agentLabel(agent) {
  if (agent?.display_status === "running") return "Working";
  if (agent?.display_status === "ooo" || agent?.paused) return "Out of office";
  if (agent?.display_status === "offline") return "Offline";
  return "Available";
}

export function taskLabel(status) {
  return (
    {
      ready: "Ready",
      queued: "Queued",
      running: "Running",
      succeeded: "Done",
      failed: "Failed",
      stopped: "Stopped",
      open: "Open",
      closed: "Closed",
    }[status] || status || ""
  );
}

export function statusDot(value) {
  return (
    {
      running: "bg-emerald-400",
      idle: "bg-zinc-500",
      ooo: "bg-amber-400",
      paused: "bg-amber-400",
      offline: "bg-zinc-600",
      ready: "bg-sky-400",
      queued: "bg-indigo-400",
      succeeded: "bg-emerald-400",
      failed: "bg-red-400",
      stopped: "bg-amber-400",
      open: "bg-sky-400",
      closed: "bg-zinc-600",
    }[value] || "bg-zinc-500"
  );
}
