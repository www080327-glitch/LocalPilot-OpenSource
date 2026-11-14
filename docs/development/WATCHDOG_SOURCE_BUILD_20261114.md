# Watchdog 6.0.0 macOS wheel 来源

PyPI 6.0.0 未提供 CPython 3.14 universal2 wheel。运行时锁使用的 wheel 是从 [官方源码包](https://pypi.org/project/watchdog/6.0.0/#files) 本地构建的，不是 PyPI 发布的二进制。源码 SHA-256 `9ddf7c82fda3ae8e24decda1338ede66e1c99883db93711d8fb941eaa2d8c282`，Apache-2.0；wheel 保留许可证。旧 APP 中哈希 `df0771e22978c47029f34141bb9aa0a9b868191265d980766949aefc9080ff2c` 的 wheel 来源不能证明，不用于新构建。

本机受控构建使用 macOS arm64、Python 3.14.6、Apple clang 21.0.0、SDK 27.2。独立构建环境的三个工具 wheel 均从 PyPI 下载并校验官方 SHA-256：

- setuptools 84.2.0：`8cc107ac7a403105dc8d6477664171f36135fab26adf8b5e0edaebc313f39b21`
- wheel 0.48.0：`3217dcc807155e45db462d7ef2431f5ddda0d7273b700d05a67b271ceb1287ab`
- packaging 26.3：`d7193f7c8e4e93f444fde0262bf90af30e16fa0ad0ad44cb553c87339b23cd1c`

将校验后的工具安装进独立 Python 3.14.6 环境，然后执行：

```sh
python desktop/scripts/build-watchdog-wheel.py --source /path/to/watchdog-6.0.0.tar.gz --out /fresh/dependencies
```

脚本校验源包、工具版本、目标不存在和产物 SHA-256，并固定编译环境；不联网，不使用旧 APP。wheel 哈希为 `c1d1d020f564cdec2ea437ff1304e47c182fe19d4310d3eb0923c33158025ab5`。本机不同源码路径的干净编译一致；不同编译器、SDK 或系统可能产生不同结果，脚本会拒绝不匹配的输出，不自动修改锁。构建证据和测试限制见 [验收记录](../evidence/nationals-20261114-head-retest/RESULTS.md)。
