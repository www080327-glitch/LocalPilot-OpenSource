"""Synthetic narration for a disclosed live SDK demonstration."""
import json
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'.aic-runtime/narration';OUT.mkdir(parents=True,exist_ok=False)
SCENES=[
 (0,'这是大肥鱼队的参赛作品，localpilot。画面展示独立 Core 的实时接口调用。所有文件均为本轮生成的公开测试文件。'),
 (20,'模型推荐器与本地云端路由分别负责不同决策。轻量 MLP 预测吞吐量，先经过内存和上下文约束。缺少任务质量校准时，明确回退旧规则。'),
 (45,'现在提交一个真实云端任务。模型读取文件，报告两个数字及其总和。文件内容没有预先放进问题中。运行时保留任务编号和工具收据。独立验证器再检查文件哈希和最终标记。这个小任务演示实际执行与验证流程，不代表公开基准的总体成功率。'),
 (115,'再次使用相同请求和幂等键，系统返回原任务编号。随后停止并重建本轮 Core，仍能查询原来的状态和收据。恢复持久状态不会重放已经完成的操作。'),
 (155,'完全权限也有授权边界。这里尝试读取授权目录以外的合成文件，路径检查直接拒绝。测试没有替模型自动批准越权操作。'),
 (185,'费用账本记录每一次请求，包括失败和重试。费用按官方标准价格估算，实际账单仍待核对。缓存命中由服务端 Token 计数证明。命中并不保证延迟降低，这组热请求反而更慢。'),
 (215,'我们的目标，是在尽量保持任务质量的同时减少云端成本。这是需要实验检验的目标。报告保留失败、未知和未运行项目。自有代码采用 MIT 许可，比赛期间保持私有，赛后计划公开。')]

for index,(start,text) in enumerate(SCENES):
    path=OUT/f'{index}.txt';path.write_text(text)
    subprocess.run(['/usr/bin/say','-v','Tingting','-r','210','--file-format=WAVE','--data-format=LEI16@22050','-f',str(path),'-o',str(OUT/f'{index}.wav')],check=True)
(OUT/'scenes.json').write_text(json.dumps(SCENES,ensure_ascii=False,indent=2))
print('Narration generated with macOS speech synthesis; not a human recording.')
