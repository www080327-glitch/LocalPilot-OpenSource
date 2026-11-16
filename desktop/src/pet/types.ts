export type Rect = [number, number, number, number];
export interface SpriteImage {
  url: string;
  width: number;
  height: number;
}
export interface EdgePack extends Partial<SpriteImage> {
  status: string;
  extras?: Record<string, SpriteImage>;
}
export interface PetAsset extends Partial<SpriteImage> {
  status: string;
  id?: string;
  label?: string;
  edge?: EdgePack;
}
export interface RenderPart {
  source: "pending" | "legacy" | "edge" | "comic" | "tail";
  rect: Rect;
  box: Rect;
  opacity: number;
  angle: number;
}
export interface EdgePresentation {
  anchor: string;
  mode: string;
  direction: string;
  activity: string;
  motion: boolean;
  phase: number;
  render: RenderPart & {
    tail: RenderPart | null;
    water: number;
    frame: [number, number];
  };
  chat_box: Rect;
  mini_visible: boolean;
  mini_glass: boolean;
  thought_left: boolean;
  thought_up: boolean;
}
