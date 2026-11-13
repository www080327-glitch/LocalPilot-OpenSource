import { Folder, MessageSquare, Pin, FolderInput } from "lucide-react";
import type { Task, Json } from "../domain";
import { label, isUnknown } from "../domain";
import type { ProjectGroup } from "../projects";
import { conversationTitle } from "../conversations";

export function ProjectHistory({
  groups,
  allTasks,
  turns,
  titles,
  currentSession,
  pinnedSessions,
  onOpen,
  onPinProject,
  onPinSession,
  onMoveSession,
}: {
  groups: ProjectGroup[];
  allTasks: Task[];
  turns: Record<string, Json>;
  titles: Record<string, string>;
  currentSession?: string;
  pinnedSessions: string[];
  onOpen: (task: Task) => void;
  onPinProject: (project: string) => void;
  onPinSession: (session: string) => void;
  onMoveSession: (session: string) => void;
}) {
  return (
    <div className="project-groups">
      {groups.map((group) => (
        <section className="project-group" key={group.name}>
          <div className="project-group-heading">
            <Folder size={13} />
            <strong>{group.name}</strong>
            <button className="icon-btn" title={group.pinned ? "取消项目置顶" : "置顶项目"}
              aria-label={group.pinned ? `取消置顶项目 ${group.name}` : `置顶项目 ${group.name}`}
              onClick={() => onPinProject(group.name)}>
              <Pin size={12} fill={group.pinned ? "currentColor" : "none"} />
            </button>
          </div>
          {group.tasks.map((task) => (
            <div className="project-task-row" key={task.id}>
              <button className={`task-row ${currentSession === task.session_id ? "selected" : ""}`}
                onClick={() => onOpen(task)}>
                <MessageSquare size={14} />
                <span>{conversationTitle(task, allTasks, titles, turns)}
                  <small>{label(task.status)}</small>
                </span>
                <i className={`task-dot ${task.status === "completed" ? "good" :
                  isUnknown(task) || task.status.includes("requires") ? "warn" : ""}`} />
              </button>
              <button className="icon-btn project-row-action"
                aria-label={pinnedSessions.includes(task.session_id) ? "取消置顶会话" : "置顶会话"}
                title="置顶／取消置顶会话" onClick={() => onPinSession(task.session_id)}>
                <Pin size={12} fill={pinnedSessions.includes(task.session_id) ? "currentColor" : "none"} />
              </button>
              <button className="icon-btn project-row-action" aria-label="移动到项目"
                title="移动到项目" onClick={() => onMoveSession(task.session_id)}>
                <FolderInput size={12} />
              </button>
            </div>
          ))}
        </section>
      ))}
    </div>
  );
}
