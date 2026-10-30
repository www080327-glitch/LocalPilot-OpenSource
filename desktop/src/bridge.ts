import { invoke, isTauri } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
export const desktop = isTauri();
export async function call<T = any>(
  command: string,
  args?: Record<string, unknown>,
): Promise<T> {
  if (!desktop)
    throw new Error(
      "请在 LocalPilot macOS 应用中连接服务。浏览器仅提供明确标记的设计预览。",
    );
  return invoke<T>(command, args);
}
export async function streamListener(fn: (event: any) => void) {
  return desktop ? listen("task-stream", (e) => fn(e.payload)) : () => {};
}
