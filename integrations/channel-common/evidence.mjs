// Task lifecycle, tool execution, delivery and independent verification are distinct.
export function evidenceOf(data) {
  const evidence = data.evidence || {};
  const count = evidence.successful_tool_receipts;
  return { successfulToolReceipts: Number.isSafeInteger(count) && count >= 0 ? count : null,
    finalDelivery: ["delivered", "blocked", "failed", "pending"].includes(evidence.delivery_status)
      ? evidence.delivery_status : "NOT_VERIFIED",
    independentVerification: "NOT_RUN", decisionUncertain: typeof data.decision_hold === "string" };
}
export function evidenceText(record) {
  if (record.kind === "help" || record.notice) return "";
  return "\n工具成功收据：" + (record.successfulToolReceipts ?? "未核实") +
    "；最终交付：" + (record.finalDelivery || "NOT_VERIFIED") +
    "；独立 Verification：NOT_RUN" +
    (record.decisionUncertain ? "\n审批响应仍为 UNKNOWN；只可查询，不能重放决定。" : "");
}
