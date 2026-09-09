# TranslatorX

发行版通过 PyAppify v1.2.3 管理 Python 3.12、依赖安装和 Git tag 更新。
首次使用建议下载 GitHub Releases 中的 `TranslatorX-win32-release-setup.exe`
（离线完整包）；`TranslatorX-win32-online-setup.exe` 为联网安装器。
win32 是上游的 Windows 平台标识，不代表应用为 32 位。
启动 `TranslatorX.exe` 后可选择自动更新与自动启动；默认更新方式为自动更新正式版本。
需要直接自动启动时可运行 `TranslatorX.exe -c start --auto-start true --update-method auto`。

## 发布与自动更新

推送 `v*` tag 自动运行 `.github/workflows/release.yml`：独立环境安装依赖、
单元测试、真实 OpenVINO OCR 检查、PyAppify 在线/离线打包、上传 GitHub Release。
Actions 页面也可手动运行（只上传构建产物，不发布 Release）。
版本使用递增语义版本；测试版本使用 `v0.1.1-beta.1` 形式，标记为预发布。
每次发布应先等待测试通过，再创建 tag；PyAppify 按 Git tag 检查更新，
并不等待 GitHub Release 安装包构建完成。请勿覆盖已经发布的 tag。

```powershell
git add .
git commit -m "Release changes"
git push origin main
git tag v0.1.1
git push origin v0.1.1
```

配置保存在 `%LOCALAPPDATA%/TranslatorX/TranslatorX/TranslatorX.ini`，
首次运行自动导入当前工作目录中旧版配置（如果存在），避免源码升级影响密钥和设置。
旧 NSIS 安装用户需安装一次新版 PyAppify 包，以后由启动器更新源码和依赖。
`installer.cfg` 仅保留用于旧 Pynsist 构建，新的 CI 不使用它。
Release 附带 PyAppify GPL 许可证、对应上游源码和品牌修改补丁，以及 SHA-256 校验表。

Windows 实时窗口 OCR 翻译工具。它使用 `onnxocr` 识别选定窗口中的文字，通过在线翻译服务翻译，并在目标窗口对应位置绘制鼠标穿透的译文层。

## 当前功能

- `onnxocr` / PP-OCRv5 ONNX 模型后台识别
- 百度、腾讯、OpenAI 兼容接口
- 译文显示在原文下方或右侧
- 所有译文矩形被限制在目标窗口内部
- 目标窗口不是前台窗口时自动隐藏译文并暂停截图
- 覆盖层保持显示但被排除在屏幕捕获之外，空 OCR 帧会保留上一帧译文，减少闪烁
- 目标窗口移动、缩放或关闭时自动跟踪
- 按目标窗口所在显示器 DPI 对齐覆盖层，支持 125%/150% 等缩放
- 翻译结果缓存，避免相同文字重复请求
- 自动忽略纯数字、纯标点/特殊符号以及孤立拉丁字母 OCR 片段
- 主界面可用滑块调整译文基准字号，默认 12 号并自动保存
- 译文使用可调的固定基准字号，并使用无背景的浅色文字与黑色描边
- 配置页可测试已配置接口并显示连通状态和延迟

## 在 oknikke 环境运行

```powershell
& 'C:\Users\baoxin\miniconda3\envs\oknikke\python.exe' run_translatorx.py
```

默认优先使用 OpenVINO OCR 加速；如果 OpenVINO 初始化失败，会自动回退到 ONNX Runtime CPU。安装包会同时包含 `openvino`、`onnxruntime` 和 PP-OCRv5 的 `onnxocr` 运行时与模型。

首次使用百度、腾讯或 OpenAI 兼容接口前，点击标题栏中的“设置”填写凭据。保存后，密钥会通过 Windows DPAPI 绑定当前用户加密存储，后续启动会自动载入；也可以使用以下环境变量：

- `TRANSLATORX_BAIDU_APP_ID`、`TRANSLATORX_BAIDU_SECRET`
- `TRANSLATORX_TENCENT_SECRET_ID`、`TRANSLATORX_TENCENT_SECRET_KEY`、`TRANSLATORX_TENCENT_REGION`
- `TRANSLATORX_OPENAI_BASE_URL`、`TRANSLATORX_OPENAI_API_KEY`、`TRANSLATORX_OPENAI_MODEL`

## 测试

```powershell
& 'C:\Users\baoxin\miniconda3\envs\oknikke\python.exe' -m pytest -q
```
