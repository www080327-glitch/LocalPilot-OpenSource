import React from "react";
import { createRoot } from "react-dom/client";
import { ChannelSettings } from "../../src/components/ChannelSettings";
import "../../src/style.css";
createRoot(document.getElementById("root")!).render(
  <main style={{ padding: 24, maxWidth: 850, margin: "auto" }}>
    <ChannelSettings onError={() => {}} onboarding />
  </main>,
);
