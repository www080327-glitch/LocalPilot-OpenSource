from catalog import CONTEXT_LENGTHS
from hardware import get_hardware
from recommender import recommend_primary as recommend
from agent.__main__ import main as agent_main
import sys


PREFERENCES = {
    "1": "quality",
    "2": "speed",
    "3": "efficiency",
    "4": "balanced",
}

MODEL_CONTEXT_PREFERENCES = {
    "1": "model",
    "2": "slight_model",
    "3": "balanced",
    "4": "slight_context",
    "5": "context",
}

LOCAL_STRATEGIES = {
    "1": "local_only",
    "2": "local_first",
    "3": "balanced",
    "4": "cloud_first",
    "5": "cloud_only",
}


def main(agent_args=None):
    agent_args = list(agent_args or [])
    verbose = "--verbose" in agent_args or "--debug-trace" in agent_args
    agent_args = [arg for arg in agent_args if arg != "--verbose"]
    hardware = get_hardware()
    memory_gb = hardware["memory"]

    print("检测到设备：")
    print(f"{hardware['chip']} / {hardware['computer']}")
    print(f"统一内存：{memory_gb if memory_gb is not None else '未知'} GB")
    print(f"系统：{hardware['os']} ({hardware['arch']})")
    if hardware.get("platform_status") != "supported":
        print(f"平台状态：{hardware.get('platform_status')} — {hardware.get('platform_reason')}")
        return

    print("\n请选择偏好：\n1. 效果优先\n2. 速度优先\n3. 资源偏好（heuristic，未测能耗）\n4. 平衡")
    preference = PREFERENCES.get(input("请输入编号：").strip(), "balanced")

    print("\n请选择希望使用的最大上下文：")
    for index, context_k in enumerate(CONTEXT_LENGTHS, start=1):
        print(f"{index}. {context_k}K")
    context_choice = input("请输入编号：").strip()
    try:
        context_k = CONTEXT_LENGTHS[int(context_choice) - 1]
    except (ValueError, IndexError):
        context_k = 32
        print("输入无效，使用 32K。")

    print("\n请选择模型能力与上下文容量的取舍：")
    print("1. 模型能力优先\n2. 稍偏模型能力\n3. 平衡\n4. 稍偏长上下文\n5. 上下文容量优先")
    model_context = MODEL_CONTEXT_PREFERENCES.get(input("请输入编号：").strip(), "balanced")

    result = recommend(memory_gb, preference, context_k, model_context, chip=hardware.get("chip"))
    if result is None:
        print("\n当前内存下没有符合安全余量的模型组合。进入 Agent 会话，可使用云端模型。")
        return agent_main(["--workspace", ".", *agent_args])
    if result.get("status") in {"unsupported", "deferred"}:
        print(f"\n平台暂不支持：{result['reason']}")
        return

    print("\n推荐配置：")
    print(f"模型：{result['model']['name']}")
    print(f"建议上下文：{result['context_k']}K" +
          (f"（请求 {context_k}K）" if result['context_k'] < context_k else ""))
    print(f"原因：{result['reason']}")
    if verbose:
        print(f"仓库：{result['model_id']}")
        print(f"量化：{result['quantization']} ({result['backend']})")
        print(f"估算准入包络：{result['estimated_peak_memory_gb']} GiB + {result['system_reserve_gb']} GB 系统预留")
        print(f"数据来源：{result['data_source']} — {result['estimate_reason']}")
        print(f"排序依据：{result.get('ranking_provenance', 'unknown')}")

    print("\n即将进入 Agent 会话；默认 balanced，可用 /policy 随时调整。")
    return agent_main(["--workspace", ".", *agent_args], recommendation=result)


if __name__ == "__main__":
    main(sys.argv[1:])
