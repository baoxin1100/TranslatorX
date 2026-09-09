# TranslatorX

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

默认使用 ONNX Runtime CPU，兼容性更稳；确认本机 OpenVINO 驱动正常后，可在主页面打开“OpenVINO OCR 加速”开关，重启后启用。

首次使用百度、腾讯或 OpenAI 兼容接口前，点击标题栏中的“设置”填写凭据。保存后，密钥会通过 Windows DPAPI 绑定当前用户加密存储，后续启动会自动载入；也可以使用以下环境变量：

- `TRANSLATORX_BAIDU_APP_ID`、`TRANSLATORX_BAIDU_SECRET`
- `TRANSLATORX_TENCENT_SECRET_ID`、`TRANSLATORX_TENCENT_SECRET_KEY`、`TRANSLATORX_TENCENT_REGION`
- `TRANSLATORX_OPENAI_BASE_URL`、`TRANSLATORX_OPENAI_API_KEY`、`TRANSLATORX_OPENAI_MODEL`

## 测试

```powershell
& 'C:\Users\baoxin\miniconda3\envs\oknikke\python.exe' -m pytest -q
```
