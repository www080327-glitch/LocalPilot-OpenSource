import React, { useState } from "react";
import { createRoot } from "react-dom/client";
import {
  AttachmentCards,
  DocumentPanel,
} from "../../src/components/Attachments";
import "../../src/style.css";
import { DocumentLink } from "../../src/documentReferences";
function Fixture() {
  const [files, setFiles] = useState([
    { id: "selected", name: "note.txt", size: 100 },
  ]);
  return (
    <main>
      <DocumentLink href={`lpdoc:att_${"0".repeat(32)}:3:${"1".repeat(64)}`}>
        查看引用来源
      </DocumentLink>
      <AttachmentCards
        files={files}
        onRemove={(id) => setFiles((old) => old.filter((f) => f.id !== id))}
        onError={(e) => {
          throw e;
        }}
      />
      <DocumentPanel
        sessionId="fixture-session"
        onError={(e) => {
          throw e;
        }}
      />
    </main>
  );
}
createRoot(document.getElementById("root")!).render(<Fixture />);
