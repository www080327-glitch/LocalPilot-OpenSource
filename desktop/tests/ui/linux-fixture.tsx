import React from "react";
import { createRoot } from "react-dom/client";
import { VersionManagement } from "../../src/components/VersionManagement";
import { TrainingSamples } from "../../src/components/TrainingSamples";
import "../../src/style.css";

createRoot(document.getElementById("root")!).render(
  <main style={{ padding: 24, maxWidth: 900, margin: "auto" }}>
    {location.search.includes("training") ? (
      <TrainingSamples />
    ) : (
      <VersionManagement health={null} cliReady />
    )}
  </main>,
);
