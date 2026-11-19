import type { PetAsset } from "./types";

export interface PetSettings {
  version: number;
  topmost: boolean;
  size: number;
  animation: boolean;
  basic_appearance: boolean;
  quiet: boolean;
  focus: boolean;
  proactive: boolean;
  banter: boolean;
  cooldown_minutes: number;
  daily_limit: number;
  quiet_start: number;
  quiet_end: number;
  event_allowlist: string[];
}
export const defaults: PetSettings = {
  version: 1,
  topmost: true,
  size: 1,
  animation: true,
  basic_appearance: false,
  quiet: false,
  focus: true,
  proactive: false,
  banter: true,
  cooldown_minutes: 30,
  daily_limit: 4,
  quiet_start: 22,
  quiet_end: 8,
  event_allowlist: [
    "explicit_reminder",
    "localpilot_completed",
    "repeated_error",
  ],
};
export function eligible(
  settings: PetSettings,
  notice: any,
  quiet: boolean,
  now: Date,
  deliveries: number[],
): boolean {
  const hour = now.getHours(),
    { quiet_start: a, quiet_end: b } = settings;
  const night =
    a === b ? false : a < b ? hour >= a && hour < b : hour >= a || hour < b;
  return (
    settings.proactive &&
    !settings.quiet &&
    !settings.focus &&
    !quiet &&
    !night &&
    notice.status === "pending" &&
    notice.delivery === "popup_available" &&
    settings.event_allowlist.includes(notice.type) &&
    deliveries.filter((t) => new Date(t).toDateString() === now.toDateString())
      .length < settings.daily_limit &&
    (!deliveries.length ||
      now.getTime() - deliveries.at(-1)! >= settings.cooldown_minutes * 60000)
  );
}

export function edgeImportHint(
  asset: PetAsset | null,
  status = asset?.edge?.status,
) {
  if (!asset) return "正在读取本机角色";
  if (asset.status === "asset_pending")
    return "在宠物设置的“换个形象”中选择角色";
  if (!asset.id) return "图集已导入。请在“换个形象”中选择对应角色";
  if (status === "invalid") return "姿态包无法加载，请在宠物设置中重新导入";
  return "请在宠物设置中导入当前角色的探头姿态包";
}
