import { useEffect, useRef, useState } from "react";
import { call, desktop } from "../bridge";

export function useReducedMotion(
  character: boolean,
  onError: (error: unknown) => void,
) {
  const report = useRef(onError);
  report.current = onError;
  const [reduced, setReduced] = useState(
    () => window.matchMedia("(prefers-reduced-motion: reduce)").matches,
  );
  useEffect(() => {
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => {
      setReduced(media.matches);
      if (desktop && character)
        void call("pet_action", {
          action: "motion_preference",
          value: media.matches,
        }).catch((error) => report.current(error));
    };
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, [character]);
  return reduced;
}
