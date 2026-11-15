import React from "react";
import { createRoot } from "react-dom/client";
import { SetupAssistant } from "../../src/components/SetupAssistant";
import { ModelLibrary } from "../../src/components/ModelLibrary";
import "../../src/style.css";

const models = [
  {
    id: "cpu-fixture",
    model: "Fixture GGUF",
    adapter: "local-openai",
    deployment_status: "ready",
    cloud_egress: "LOCAL_ONLY",
    capabilities: ["tool_calling"],
  },
];
createRoot(document.getElementById("root")!).render(
  <main style={{ padding: 24, maxWidth: 850, margin: "auto" }}>
    {location.search.includes("library") ? (
      <ModelLibrary models={models} />
    ) : (
      <SetupAssistant
        onReady={async () => {}}
        onError={(error) => {
          throw error;
        }}
      />
    )}
  </main>,
);
