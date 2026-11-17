import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { LocalEndpointForm } from "../src/components/LocalEndpointForm";
import { ModelConfiguration } from "../src/components/ModelConfiguration";

describe("local CPU endpoint configuration", () => {
  it("offers model discovery without claiming an inference or context check", () => {
    const html = renderToStaticMarkup(<LocalEndpointForm />);
    expect(html).toContain("检查连接并读取模型列表");
    expect(html).toContain("不发送推理请求");
    expect(html).toContain('placeholder="填写推理服务实际配置的上限" value=""');
    expect(html).toContain("模型列表不能证明上下文容量");
    expect(html).not.toContain("下载 MLX");
  });

  it("makes Companion power and model thinking explicit choices", () => {
    const html = renderToStaticMarkup(<LocalEndpointForm />);
    expect(html).toContain(
      '<option value="system" selected="">跟随系统电源策略</option>',
    );
    expect(html).toContain("不改变系统电源设置");
    expect(html).toContain("请求后端关闭模型思考输出");
    expect(html).toContain("是否生效仍需实际回答验证");
  });

  it("shows the shared endpoint form first for Intel configuration", () => {
    const html = renderToStaticMarkup(<ModelConfiguration preferEndpoint />);
    expect(html).toContain(
      '<details open="" class="advanced-settings"><summary>Intel / CPU',
    );
    expect(html).toContain(
      '<details class="advanced-settings"><summary>由多个已注册模型协作</summary>',
    );
    expect(html).toContain("llama.cpp");
    expect(html).toContain('value="http://127.0.0.1:1234/v1"');
  });

  it("keeps cooperation available in the normal model configuration view", () => {
    const html = renderToStaticMarkup(<ModelConfiguration />);
    expect(html).toContain(
      '<details open="" class="advanced-settings"><summary>由多个已注册模型协作</summary>',
    );
    expect(html).toContain("保存协作 Agent 配置");
    expect(html).toContain("保存本机模型配置");
  });

  it("offers optional read-only roles while Super Agent keeps coordination", () => {
    const html = renderToStaticMarkup(<ModelConfiguration />);
    expect(html).toContain('aria-label="探索模型（只读）" disabled=""');
    expect(html).toContain('aria-label="审阅模型（只读）" disabled=""');
    expect(html).toContain("Super Agent 负责统筹");
    expect(html).toContain("可使用同一伙伴模型");
    expect(html).toContain("测试由执行 Agent 负责");
    expect(html).toContain("来源策略仍决定允许使用的本地或云端模型");
  });
});
