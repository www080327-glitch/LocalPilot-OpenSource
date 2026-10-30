import type { Json, Model } from "./domain";

// Selection grants one bounded load; never unload another model or retry UNKNOWN.
export async function ensureLocalModelLoaded(
  model: Model,
  invoke: <T = Json>(name: string, args: Json) => Promise<T>,
) {
  if (model.adapter !== "omlx") return;
  const catalog = await invoke<Json>("model_manager", {
    operation: "catalog",
    id: null,
  });
  const entry = catalog.models?.models?.find((m: Json) => m.id === model.model);
  if (
    !entry ||
    entry.files_present === false ||
    entry.deployment_status === "not_deployed"
  )
    throw new Error(
      "这个模型的文件还没有下载完整。请在模型库下载，或选择已有完整模型。",
    );
  if (entry.loaded) return;
  if (entry.deployment_status === "loading")
    throw new Error("模型正在加载，请稍候再发送。不会重复发起加载。");
  if (!catalog.resources_supported)
    throw new Error("当前服务不支持自动加载，请在模型库中加载模型。");
  if (typeof entry.size_bytes !== "number" || entry.size_bytes <= 0)
    throw new Error("无法确认模型所需内存，请在模型库检查模型信息。");
  await invoke("model_resource", {
    model: model.id,
    operation: "load",
    confirmed: true,
    maxMemoryBytes: Math.ceil(entry.size_bytes * 1.2 + 2 * 1024 ** 3),
  });
}
