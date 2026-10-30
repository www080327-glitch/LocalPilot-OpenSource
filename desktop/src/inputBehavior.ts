export type EnterBehavior = "newline" | "send";
export interface EnterKey {
  key: string;
  shiftKey: boolean;
  altKey: boolean;
  metaKey: boolean;
  ctrlKey: boolean;
  isComposing?: boolean;
  keyCode?: number;
}
// WebKit can end composition just before the confirming Enter keydown.
export function shouldSubmitEnter(
  event: EnterKey,
  behavior: EnterBehavior,
  composing: boolean,
  lastCompositionEnd: number,
  now: number,
) {
  if (
    event.key !== "Enter" ||
    composing ||
    event.isComposing ||
    event.keyCode === 229 ||
    now - lastCompositionEnd < 100
  )
    return false;
  if (event.shiftKey || event.altKey) return false;
  return event.metaKey || event.ctrlKey || behavior === "send";
}
