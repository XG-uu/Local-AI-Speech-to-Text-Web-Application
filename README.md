# 本地语音识别 Web 系统

基于 **B/S 架构** 的本地中文 / 英文语音识别系统。浏览器负责录音或上传音频，后端使用 **faster-whisper** 在 **CPU** 上完成本地推理，音频不会上传到任何云端服务。

## 功能

- 麦克风录音识别，最长 60 秒，自动停止并提示。
- 上传音频识别，支持 WAV、WebM/Opus、OGG、MP3、M4A 等可解码格式，最大 10 MB。
- 中文 / English 语言选择，另有自动语言检测（实验）。
- 识别结果、音频时长、处理耗时、模型信息展示，一键复制。
- 完整的异常提示：权限拒绝、无麦克风、空文件、损坏文件、格式不支持、模型未下载、推理失败等。
- 近实时语音识别（加分项）：录音过程中通过 WebSocket 持续显示临时文本，停止后输出最终结果。
- 默认测试使用 Fake 引擎，不下载模型、不访问麦克风；真实模型测试单独执行。

## 环境要求

| 项目 | 要求 |
| --- | --- |
| Python | **3.12**（必须） |
| 操作系统 | Windows 11 x64（已验证），macOS / Linux 亦可 |
| 浏览器 | Chrome / Edge 最新稳定版 |
| 硬件 | 普通 CPU 即可，无需 GPU / CUDA |
| 网络 | 首次安装依赖和下载模型需要联网，之后可离线识别 |

> 如果系统默认 `python` 不是 3.12，请使用 3.12 解释器创建虚拟环境。Windows 上可通过官方安装包或 `py -3.12` / 具体路径调用。

## 快速开始

```bash
# 1. 进入项目目录
cd 本地语音识别Web系统

# 2. 创建并激活 Python 3.12 虚拟环境（Windows）
python3.12 -m venv .venv
# 若 python3.12 不在 PATH，可改用 py -3.12 或 Python 3.12 的完整路径
.venv\Scripts\activate

# 3. 安装依赖
python -m pip install -r requirements.txt

# 4. 预下载模型（推荐；首次识别也会自动下载）
python -m app.scripts.download_model

# 5. 启动服务
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

打开浏览器访问：

```text
http://127.0.0.1:8000
```

### 使用步骤

1. 选择识别语言：中文 / English / 自动检测。
2. 录音：点击“开始录音”，允许麦克风权限，讲话后点击“停止录音”；达到 60 秒会自动停止。
3. 上传：选择或拖入音频文件，点击“上传并识别”。
4. 查看识别文本、音频时长、处理耗时，点击“复制文本”。
5. 实时模式：勾选“实时识别（实验）”后开始录音，录音过程中会持续显示临时文本；停止后显示最终结果。

## 模型说明

### 选型

使用 **faster-whisper** 的 **small 多语言模型**，通过 CTranslate2 在 CPU 上以 `int8` 推理：

- 单一模型覆盖中文和英文，无需两套权重。
- CPU 可运行，不要求 NVIDIA GPU / CUDA。
- 模型约 460 MB，普通开发电脑内存可承受。
- PyAV 解码，不依赖系统安装 ffmpeg。
- 运行期完全本地，不调用 OpenAI / Azure / Google 等云端 ASR。

### 下载与离线

模型默认保存到项目下的 `models/small/`（已被 `.gitignore` 忽略）。

```bash
# 联网预下载
python -m app.scripts.download_model
```

下载后断开网络仍可识别。强制离线模式：

```bash
# Windows PowerShell
$env:ASR_OFFLINE="1"
$env:HF_HUB_OFFLINE="1"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

离线模式下若本地没有模型，接口会返回 `503 model_unavailable`，并提示先执行下载脚本。

### 切换模型

```bash
# 可选：base（更快、准确率略低）、medium（更慢、更准）
$env:ASR_MODEL="base"
```

切换模型后需要重新下载对应权重。

## 接口

### `GET /health`

```json
{ "status": "ok" }
```

不触发模型加载，适合健康检查。

### `GET /api/status`

返回模型名、设备、是否已加载、上传/录音限制等信息，供页面展示。

### `GET /v1/models`（工具兼容）

返回空模型列表：

```json
{ "object": "list", "data": [] }
```

该接口不是本项目的业务功能。OpenCode 内置的 vLLM 本地发现会探测 `http://127.0.0.1:8000`，先请求 `/health`，再请求 `/v1/models`。本项目是语音识别服务，不是 LLM 服务，因此返回空列表，既避免探测产生误导性的 404，也不提供任何聊天模型。该路由不出现在 `/docs` 中。

### `POST /api/transcribe`

`multipart/form-data`：

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `file` | File | 是 | 音频文件，最大 10 MB |
| `language` | String | 是 | `zh` / `en`；`auto` 为实验功能 |
| `source` | String | 否 | `recording` / `upload`，默认 `upload` |

成功响应：

```json
{
  "text": "你好，欢迎使用本地语音识别系统。",
  "language": "zh",
  "duration_seconds": 8.69,
  "processing_seconds": 2.31,
  "model": "small",
  "requested_language": "zh",
  "no_speech": false,
  "segments": [
    { "start": 0.0, "end": 8.5, "text": "你好，欢迎使用本地语音识别系统。" }
  ]
}
```

`model`、`requested_language`、`no_speech`、`segments` 为扩展字段，不影响必做契约。

错误响应统一为：

```json
{ "detail": "无法解码该音频文件，请确认文件未损坏。", "code": "decode_failed" }
```

常用错误码：

| HTTP | code | 场景 |
| --- | --- | --- |
| 400 | `empty_file` | 空文件 |
| 400 | `unsupported_audio` / `decode_failed` | 格式不支持 / 解码失败 |
| 400 | `invalid_language` | 非法语言 |
| 400 | `recording_too_long` | 录音超过 60 秒 |
| 413 | `file_too_large` | 超过 10 MB |
| 422 | `validation_error` | 缺少 file/language 等参数 |
| 503 | `model_unavailable` | 模型未下载或加载失败 |
| 500 | `inference_failed` | 推理失败 |

### `GET /`

返回 Web 页面。

### `WS /ws/transcribe`（扩展）

实时识别 WebSocket：

1. 连接 `/ws/transcribe?language=zh`。
2. 发送 `{"type":"start","language":"zh"}`，收到 `{"type":"ready","sample_rate":16000}`。
3. 持续发送 16 kHz / 16-bit / 单声道小端 PCM 二进制分片。
4. 收到 `{"type":"partial","text":"...","duration_seconds":3.2}`。
5. 发送 `{"type":"stop"}`，收到 `{"type":"final", ...}` 后连接关闭。

## 测试

### 默认自动化测试（无需模型、无需麦克风）

```bash
python -m pytest -q
```

覆盖：

- `/health`、`/api/status`、`/v1/models`、页面与静态资源。
- 中文/英文/自动语言转写。
- 非法语言、非法 source、缺文件、空文件、损坏文件、超大文件。
- 录音 60 秒校验、上传时长可选限制。
- 模型不可用、推理失败、无语音。
- 音频解码、8 kHz 重采样、立体声、WebM/Opus 浏览器录音格式、静音检测。
- WebSocket 实时会话、partial/final、超长录音。
- 前后端 HTTP 识别流程。

模型调用使用 `FakeASREngine`，因此默认测试**不会**下载模型。当前基线为 `49 passed, 3 skipped`，3 个跳过项即真实模型测试。

### 真实模型测试

先下载模型，再执行：

```bash
# Windows PowerShell
$env:RUN_REAL_ASR="1"
python -m pytest -q -m real_asr
```

当前基线为 `3 passed, 49 deselected`：使用 `samples/chinese.wav` 和 `samples/english.wav` 调用本地 faster-whisper，验证识别文本包含预期关键词，并额外通过 HTTP API 走完整链路。

### 样例音频

| 文件 | 内容 | 时长 |
| --- | --- | --- |
| `samples/chinese.wav` | 中文普通话，Windows Huihui TTS 生成 | 约 8.7 秒 |
| `samples/english.wav` | 英文，Windows Zira TTS 生成 | 约 7.1 秒 |
| `samples/reference.txt` | 人工参考文本 | — |

样例由系统 TTS 合成，不包含个人敏感信息，可随项目分发。重新生成：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/generate_samples.ps1
```

## 项目结构

```text
本地语音识别Web系统/
├── app/
│   ├── main.py                 # FastAPI 入口与异常处理
│   ├── config.py               # 环境变量配置
│   ├── errors.py               # 错误码
│   ├── schemas.py              # 响应模型
│   ├── audio.py                # 解码、重采样、时长、静音检测
│   ├── realtime.py             # 实时会话缓冲与文本合并
│   ├── asr/                    # ASR 抽象、Fake、faster-whisper
│   ├── api/                    # health / transcribe / realtime
│   └── scripts/download_model.py
├── static/                     # HTML / CSS / JS
├── tests/                      # pytest 自动化测试
├── samples/                    # 中英文样例音频与参考文本
├── docs/                       # 需求、设计、测试、AI 开发与过程记录
├── models/                     # 模型权重（运行后生成，不提交）
├── requirements.txt
├── pytest.ini
└── README.md
```

## 配置项

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `ASR_MODEL` | `small` | 模型名或本地路径 |
| `ASR_DEVICE` | `cpu` | `cpu` / `cuda` |
| `ASR_COMPUTE_TYPE` | `int8` | CPU 量化类型 |
| `ASR_BEAM_SIZE` | `1` | 解码 beam 大小，越大越慢 |
| `ASR_MODEL_DIR` | `models` | 模型目录 |
| `ASR_OFFLINE` | `0` | `1` 时强制只读本地模型 |
| `ASR_VAD_FILTER` | `1` | 是否启用语音活动检测 |
| `MAX_UPLOAD_MB` | `10` | 上传大小上限 |
| `MAX_RECORDING_SECONDS` | `60` | 录音时长上限 |
| `MAX_AUDIO_SECONDS` | `0` | 上传音频总时长上限，0 表示不限制 |
| `REALTIME_CHUNK_SECONDS` | `2.5` | 实时分片识别间隔 |
| `REALTIME_OVERLAP_SECONDS` | `0.4` | 实时分片重叠 |
| `ASR_LOG_LEVEL` | `INFO` | 日志级别 |

## 性能与限制

- 首次识别需要加载模型，可能等待数秒到数十秒；页面会显示等待时间和首次加载提示。
- CPU 推理速度取决于硬件；默认使用 `small + int8 + beam_size=1` 优先速度。
- 上传只限制 10 MB，不限制音频时长；如需防护，可设置 `MAX_AUDIO_SECONDS`。
- 单进程、单模型、推理串行，定位本机单用户，不承诺多用户并发吞吐。
- 实时模式为分片重识别，临时文本可能存在抖动或边界错误；最终结果以整段识别为准。
- 不做语音翻译、降噪、说话人识别、历史记录、用户登录。
- 手机端未专门适配。

## 常见问题

**麦克风按钮无反应 / 提示不支持**

请使用最新版 Chrome 或 Edge，通过 `http://127.0.0.1:8000` 访问（localhost 属于安全上下文）。

**权限被拒绝**

点击地址栏左侧的站点设置，将麦克风权限改为“允许”，刷新页面后重试。

**首次识别很慢**

首次需要加载本地模型；可先执行 `python -m app.scripts.download_model` 并观察日志。后续识别会明显加快。

**模型下载失败**

检查网络或代理设置。若本机设置了 `HF_ENDPOINT=https://hf-mirror.com` 且镜像返回 500，可临时改用官方端点后重试：

```powershell
$env:HF_ENDPOINT="https://huggingface.co"
# 如需要代理：
$env:HTTPS_PROXY="http://127.0.0.1:<代理端口>"
python -m app.scripts.download_model
```

也可手动下载 `Systran/faster-whisper-small` 的文件，放入 `models/small/`，至少包含 `model.bin`、`config.json`、`tokenizer.json`、`vocabulary.txt`。

**上传 WebM 失败**

确认文件可正常播放，且大小不超过 10 MB。后端使用 PyAV 解码，常见 WebM/Opus 文件均可处理。

**日志中出现 `GET /v1/models`**

这是 OpenCode 内置 vLLM 本地发现对 `127.0.0.1:8000` 的探测（先 `/health` 再 `/v1/models`），不是页面或后端发起的请求，也不影响语音识别。服务会返回 200 和空模型列表；如果不使用 OpenCode，可忽略该日志。

## 提交文档

| 文档 | 内容 |
| --- | --- |
| [README.md](README.md) | 系统介绍、环境要求、安装与启动、模型初始化、接口、测试方法 |
| [docs/requirements.md](docs/requirements.md) | 需求理解、F1–F6 功能拆分、接口契约、假设与边界条件、验收标准 |
| [docs/design.md](docs/design.md) | 总体架构、核心模块、音频处理流程、ASR 选型与实时识别设计 |
| [docs/test-report.md](docs/test-report.md) | 测试环境、用例清单、实际结果、真实模型测试、E2E 与已知问题 |
| [docs/ai-development.md](docs/ai-development.md) | OpenCode 承担的任务、关键技术决策、问题处理、验收方式与改进方向 |
| [docs/opencode-development.md](docs/opencode-development.md) | 三阶段开发过程记录：需求与设计、功能开发与集成、测试与问题定位（脱敏摘要） |

> 过程记录为关键会话与命令证据的脱敏摘要，已移除 API Key、代理凭据、本机用户名和绝对路径；完整聊天历史不属于提交物。
