export const permissionModes = [
  {
    id: "isolated",
    name: "严格隔离",
    description: "仅限当前范围，每项操作先确认。",
  },
  {
    id: "request",
    name: "请求批准",
    description: "直接读取合法文件；修改和 Shell 操作请求一次批准。",
  },
  {
    id: "workspace",
    name: "工作区自动",
    description: "自动处理工作区文件；范围外修改和 Shell 先请求批准。",
  },
  {
    id: "full",
    name: "完全权限",
    description: "自主读写合法文件和运行受保护的 Shell；联网单独确认。",
  },
];
export const legacyPermissions = [
  { id: "ask", name: "原有：逐项批准" },
  { id: "safe", name: "原有：低风险自动" },
  { id: "uncertain", name: "原有：较高风险自动" },
];
export const permissionNames: Record<string, string> = Object.fromEntries(
  [...permissionModes, ...legacyPermissions].map((p) => [p.id, p.name]),
);
export function approvalSummary(action: any) {
  const request = action?.requests?.[0] || {};
  const scope = request.scope_request || request.preview?.scope_request;
  const risk = request.preview?.risk_summary;
  const operation = request.name || risk?.operation || request.kind;
  const names: Record<string, string> = {
    apply_patch: "编辑文件",
    make_directory: "创建文件夹",
    move_file: "移动文件",
    copy_file: "复制文件",
    read_file: "读取文件",
    list_entries: "查看文件夹",
    list_directory: "查看文件夹",
    file_info: "查看文件信息",
    inspect_file: "查看文件信息",
  };
  return {
    title: scope ? "需要访问工作区外的文件" : "需要你的批准",
    operation: names[operation] || operation || "待确认操作",
    targets: scope?.targets || risk?.resource?.targets || [],
    reason: scope
      ? "只允许下面这一次操作；不会保存目录授权。"
      : "请核对操作与影响。批准仅适用于当前动作。",
    risk:
      scope?.risk === "file_mutation"
        ? "会修改文件"
        : scope?.risk === "read"
          ? "读取文件"
          : risk?.level || "查看操作详情",
  };
}
