import { defaultUrlTransform } from "react-markdown";
const reference = /^lpdoc:att_[0-9a-f]{32}:[1-9][0-9]*:[0-9a-f]{64}$/;
export const documentUrl = (url: string) =>
  reference.test(url) ? url : defaultUrlTransform(url);
export function DocumentLink({ href, children }: any) {
  return typeof href === "string" && reference.test(href) ? (
    <button
      className="reference-link"
      title="读取并核对本地来源"
      onClick={() =>
        window.dispatchEvent(
          new CustomEvent("localpilot-document-reference", {
            detail: { citation: href },
          }),
        )
      }
    >
      {children}
    </button>
  ) : (
    <span className="reference-link" title="服务内容中的链接不自动打开">
      {children}
    </span>
  );
}
