import React, { lazy, Suspense } from "react";
import { createRoot } from "react-dom/client";
import "./style.css";
const petPart = new URLSearchParams(location.search).get("pet");
if (petPart !== null) {
  document.documentElement.dataset.pet = "true";
  document.documentElement.dataset.petPart =
    new URLSearchParams(location.search).get("pet") || "character";
}
const Screen =
  petPart !== null ? lazy(() => import("./Pet")) : lazy(() => import("./App"));
createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <Suspense fallback={null}>
      <Screen />
    </Suspense>
  </React.StrictMode>,
);
