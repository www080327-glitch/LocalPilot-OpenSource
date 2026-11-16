import { listen } from "@tauri-apps/api/event";
import { desktop } from "../bridge";

export function petEvents(onError: (error: unknown) => void) {
  let closed = false;
  const stops: (() => void)[] = [];
  return {
    async on<T = any>(name: string, receive: (payload: T) => void) {
      if (!desktop) return;
      try {
        const stop = await listen<T>(name, (event) => {
          if (!closed) receive(event.payload);
        });
        if (closed) stop();
        else stops.push(stop);
      } catch (error) {
        if (!closed) onError(error);
      }
    },
    close() {
      closed = true;
      stops.forEach((stop) => stop());
    },
  };
}
