import { isUnknown, label, type Task } from "../domain";

export function TaskStatus({ task }: { task?: Task | null }) {
  const unknown = isUnknown(task);
  return (
    <span
      className={`status ${unknown ? "warn" : task?.status === "completed" ? "good" : task?.status === "failed" ? "bad" : task?.status.startsWith("requires_") ? "warn" : ""}`}
    >
      <i />
      {unknown ? "UNKNOWN · 已隔离" : task ? label(task.status) : "准备就绪"}
    </span>
  );
}
