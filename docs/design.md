# 本地语音识别 Web 系统 —— 设计说明

| 项目 | 内容 |
| --- | --- |
| 文档版本 | v1.1 |
| 日期 | 2026-11-20 |
| 关联文档 | `requirements.md`、`test-report.md`、`ai-development.md`、`opencode-development.md`、`README.md` |

## 1. 设计目标与原则

1. **本地优先**：音频与识别全部在本机完成，运行期不依赖云端 ASR。
2. **CPU 可用**：默认使用 CPU `int8` 推理，无需 CUDA，普通开发电脑可运行。
3. **依赖最小**：只用 Python + 浏览器原生能力，不引入 Node.js、数据库、Docker、外部 ffmpeg。
4. **契约稳定**：必做接口严格按需求实现，扩展字段/接口不破坏原有调用方。
5. **可测试**：ASR 引擎抽象为接口，默认测试使用 Fake 引擎；真实模型测试单独执行。
6. **失败可恢复**：所有异常转换为明确状态码与中文提示，页面可重试。

## 2. 总体架构

```text
┌──────────────────────────────────────────────────────────────┐
│ Browser (Chrome / Edge)                                      │
│  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐  │
│  │ MediaRecorder  │  │ File Input     │  │ Web Audio PCM  │  │
│  │ (录音 WebM)     │  │ (上传音频)      │  │ (实时分片)      │  │
│  └───────┬────────┘  └───────┬────────┘  └───────┬────────┘  │
│          │ multipart         │ multipart         │ WebSocket  │
└──────────┼───────────────────┼───────────────────┼───────────┘
           ▼                   ▼                   ▼
┌──────────────────────────────────────────────────────────────┐
│ FastAPI (127.0.0.1:8000)                                     │
│  /health      /api/status      /api/transcribe   /ws/transcribe│
│      │             │                 │                │       │
│      │             │        ┌────────▼────────┐       │       │
│      │             │        │ 音频处理流水线   │       │       │
│      │             │        │ 校验→解码→重采样 │       │       │
│      │             │        │ →时长→静音检测   │       │       │
│      │             │        └────────┬────────┘       │       │
│      │             │                 │                │       │
│      │             └──────────┬──────┴────────────────┘       │
│      │                        ▼                               │
│      │              ┌─────────────────────┐                   │
│      │              │ ASR Engine 抽象接口  │                   │
│      │              │ (Fake / Whisper)    │                   │
│      │              └──────────┬──────────┘                   │
│      │                         ▼                              │
│      │              ┌─────────────────────┐                   │
│      │              │ faster-whisper small│                   │
│      │              │ CTranslate2 int8    │                   │
│      │              │ models/ 本地权重     │                   │
│      │              └─────────────────────┘                   │
│      └──────────────► static/ 前端静态资源                     │
└──────────────────────────────────────────────────────────────┘
```

请求路径：

- 录音（普通）：Browser MediaRecorder → WebM Blob → `POST /api/transcribe`。
- 上传：File → `POST /api/transcribe`。
- 实时：AudioWorklet PCM → WebSocket 二进制帧 → 增量识别 → `partial` / `final`。
- 页面：`GET /` → `static/index.html`，CSS/JS 由 `/static/*` 提供。

## 3. 技术选型

### 3.1 ASR 模型

**选择：`faster-whisper` + Whisper `small` 多语言模型，CPU `int8`。**

| 方案 | 优点 | 缺点 | 结论 |
| --- | --- | --- | --- |
| faster-whisper small | 中英文均衡；CPU int8 快；PyAV 解码；VAD 内置；pip 安装简单 | 首次需下载约 460 MB | **采用** |
| faster-whisper base | 更小更快 | 中文准确率明显下降 | 备选，可通过环境变量切换 |
| sherpa-onnx | CPU 极快、模型小 | 中英文需两套模型，语言切换与依赖更复杂 | 不采用 |
| FunASR / Paraformer | 中文效果好 | 英文能力弱、依赖重、模型管理复杂 | 不采用 |
| whisper.cpp | 原生 CPU 优化 | Python 绑定/编译在 Windows 上不稳定，违背“免编译”目标 | 不采用 |

选择理由：

1. 单一多语言模型同时覆盖中文和英文，满足 F3。
2. CTranslate2 `int8` 量化在普通 CPU 上可用，不依赖 CUDA。
3. `faster-whisper` 自带 Silero VAD，可过滤静音并降低无语音误识别。
4. 模型可通过 `download_root` 固定到项目 `models/`，之后可离线加载。
5. wheel 依赖完整，Windows 下无需编译。

实测（Intel Core Ultra 5 245K，CPU int8，`beam_size=1`）：

| 样例 | 音频时长 | 处理耗时 | 模型加载 |
| --- | --- | --- | --- |
| 中文 | 8.685 s | 1.549 s | 约 1.01 s（仅首次，不计入处理耗时） |
| 英文 | 7.125 s | 1.456 s | 同上 |

该结果说明 small 在普通开发 CPU 上可用；如果硬件更弱，可切换到 `base` 或关闭 VAD 进一步提速，但中文准确率会下降。

### 3.2 音频解码

选择 **PyAV**：

- wheel 内置 FFmpeg 动态库，不要求用户安装系统 ffmpeg。
- 支持 WAV、WebM/Opus、OGG、MP3、M4A 等浏览器常见格式。
- 可直接重采样为 16 kHz 单声道 `s16`，再转 `float32` 交给模型。

WAV 是必做最低保障；即使某些环境下 PyAV 解码异常，也保留标准库 `wave` 的兜底路径（仅 PCM WAV）。

### 3.3 前端

- 原生 HTML / CSS / JavaScript，无构建步骤。
- 录音：`navigator.mediaDevices.getUserMedia` + `MediaRecorder`。
- 实时：`AudioContext` + `AudioWorklet` 采集 PCM，主线程降采样到 16 kHz。
- 复制：`navigator.clipboard`，失败回退 `textarea + execCommand`。
- 所有资源本地提供，不访问 CDN。

### 3.4 实时传输

选择 **WebSocket + 原始 PCM 分片**，而不是 MediaRecorder 分片：

- MediaRecorder 的 WebM 分片后续帧通常不能独立解码，服务端处理复杂。
- 原始 PCM 分片格式稳定，服务端可直接拼接、裁剪与重采样。
- 带宽在本机 localhost 上可忽略（16 kHz × 16 bit ≈ 32 KB/s）。

## 4. 目录结构与模块职责

```text
local-speech-to-text/
├── app/
│   ├── main.py                 # create_app、生命周期、异常处理、静态资源
│   ├── config.py               # 环境变量与默认配置
│   ├── errors.py               # AppError 及错误码
│   ├── schemas.py              # Pydantic 响应模型
│   ├── audio.py                # 上传读取、解码、重采样、时长、静音判断
│   ├── asr/
│   │   ├── base.py             # ASREngine 协议、ASRResult
│   │   ├── fake.py             # 测试用 Fake 引擎
│   │   ├── whisper_engine.py   # faster-whisper 封装
│   │   └── __init__.py
│   ├── api/
│   │   ├── compat.py           # /v1/models 空模型兼容（工具探测）
│   │   ├── health.py           # /health、/api/status
│   │   ├── transcribe.py       # /api/transcribe
│   │   ├── realtime.py         # /ws/transcribe
│   │   └── __init__.py
│   ├── realtime.py             # RealtimeSession 缓冲、分片、文本合并
│   └── scripts/
│       └── download_model.py   # 预下载模型权重
├── static/
│   ├── index.html
│   ├── css/app.css
│   └── js/
│       ├── app.js
│       └── pcm-worklet.js
├── tests/
│   ├── conftest.py
│   ├── test_health.py
│   ├── test_audio.py
│   ├── test_transcribe_api.py
│   ├── test_errors.py
│   ├── test_realtime.py
│   ├── test_frontend_flow.py
│   └── test_real_asr.py
├── samples/
│   ├── chinese.wav
│   ├── english.wav
│   └── reference.txt
├── docs/
│   ├── requirements.md
│   ├── design.md
│   ├── test-report.md
│   ├── ai-development.md
│   └── opencode-development.md
├── models/                     # 模型权重，.gitignore
├── requirements.txt
├── pytest.ini
├── README.md
└── .gitignore
```

模块依赖方向：`api → audio / asr / realtime → config / errors`。`audio` 不依赖 FastAPI；`asr` 不依赖 Web 层，便于单元测试。

### 4.1 核心模块职责

| 模块 | 核心职责 | 对外接口 / 关键约束 |
| --- | --- | --- |
| `main.py` | 应用工厂、异常处理、路由与静态资源挂载 | `create_app(engine, settings)` 支持测试注入 |
| `config.py` | 环境变量、默认值与路径解析 | `Settings` 不可变，可用 `dataclasses.replace` 覆盖 |
| `errors.py` | 领域异常与 HTTP/错误码映射 | 统一 `detail + code` |
| `audio.py` | 分块读取、解码、重采样、时长、静音检测 | 输出 16 kHz 单声道 float32；不依赖 Web |
| `asr/base.py` | ASR 协议与结果模型 | `ensure_loaded` / `transcribe` / `status` |
| `asr/fake.py` | 测试替身 | 可配置固定文本、加载/推理异常 |
| `asr/whisper_engine.py` | faster-whisper 封装、懒加载、串行推理 | 本地权重优先；离线可报 503 |
| `api/transcribe.py` | HTTP 识别编排 | 校验 → 解码 → 时长 → 静音 → 推理 |
| `api/realtime.py` | WebSocket 会话与协议 | `ready` / `partial` / `final` / `error` |
| `realtime.py` | PCM 累积、分片窗口、文本去重 | 2.5 s 分片、0.4 s 重叠、60 s 上限 |
| `api/compat.py` | 开发工具探测兼容 | `/v1/models` 返回空列表，不进 OpenAPI |
| `static/` | 页面、样式、录音/上传/实时逻辑 | 无构建步骤、无 CDN |

## 5. 音频处理流水线

```text
UploadFile
  │ 分块读取，累计 > 10MB 立即 413
  ▼
bytes
  │ 空字节 → 400 empty_file
  ▼
PyAV decode（失败则 WAV 标准库兜底）
  │ 无音频流 / 解码异常 → 400 decode_failed / unsupported_audio
  ▼
重采样为 16 kHz、单声道、float32 [-1, 1]
  │
  ▼
计算 duration_seconds = samples / 16000
  │ source=recording 且 > 60s → 400 recording_too_long
  │ MAX_AUDIO_SECONDS > 0 且超限 → 400 audio_too_long
  ▼
静音检测：max(abs(samples)) < 1e-3 → 直接返回空文本（no_speech）
  ▼
ASR 推理
```

实现要点：

- 上传分块大小 1 MB，最多读取 `MAX_UPLOAD_BYTES + 1`，避免大文件占内存。
- PyAV 解码使用 `AudioResampler(format="s16", layout="mono", rate=16000)`，最后除以 32768 转 `float32`。
- `duration_seconds` 以重采样后的样本数为准，避免容器时长元数据不准。
- 静音判定只做兜底；真正无语音时仍交给 VAD，返回空文本而不是报错。
- 音频只在内存中处理，不写临时文件。

### 5.1 解码与边界处理

| 场景 | 处理方式 | 结果 |
| --- | --- | --- |
| WAV（PCM 8/16/24/32-bit） | PyAV 优先；失败时标准库 `wave` 兜底，多声道取平均 | 16 kHz mono float32 |
| WebM/Opus、OGG、MP3、M4A | PyAV + `AudioResampler` 统一重采样 | 同上 |
| 采样率不是 16 kHz | PyAV 重采样；WAV 兜底路径使用线性插值 | 时长保持 |
| NaN / Inf / 越界样本 | `nan_to_num` 后裁剪到 `[-1, 1]` | 避免模型异常 |
| 空字节 / 无采样 | 解码前或解码后检查 | `400 empty_file` / `decode_failed` |
| 静音 | 峰值 `< 1e-3` | `200` + 空文本 + `no_speech=true` |
| 录音超限 | `duration > 60.5 s`（0.5 s 容差） | `400 recording_too_long` |
| 可选的时长保护 | `MAX_AUDIO_SECONDS > 0` 且 `> 限制 + 0.5 s` | `400 audio_too_long` |

0.5 s 容差用于吸收编码器补帧、容器时间戳与重采样带来的边界误差；前端仍在 60 s 主动停止，正常录音不会触发后端上限。

## 6. ASR 集成设计

### 6.1 接口抽象

```python
class ASREngine(Protocol):
    name: str
    def ensure_loaded(self) -> None: ...
    def transcribe(
        self, audio: np.ndarray, language: str
    ) -> ASRResult: ...
    def status(self) -> dict: ...
```

`ASRResult` 包含：

- `text`：完整文本。
- `language`：实际语言（自动检测时为检测结果）。
- `segments`：`start`、`end`、`text` 列表。

`FakeASREngine` 用于单元测试，可配置固定文本、抛异常、模拟未加载等行为。

### 6.2 Whisper 引擎生命周期

- 单例，懒加载：首次 `ensure_loaded()` 时创建 `WhisperModel`。
- 模型路径解析顺序：
  1. `ASR_MODEL_DIR/<model_name>` 存在 → 作为本地路径加载，`local_files_only=True`。
  2. 否则使用模型名，通过 `download_root` 下载到 `models/`。
  3. `ASR_OFFLINE=1` 且本地不存在 → 直接报 `model_unavailable`，提示运行下载脚本。
- 加载失败记录错误信息，下一次请求允许重试；不会让整个进程崩溃。
- 加载与推理都使用 `threading.Lock`，避免并发请求同时占用 CPU 或重复加载。
- `ensure_loaded()` 在计时开始前调用，因此 `processing_seconds` 不含模型加载/下载。
- 推理通过 `asyncio.to_thread` 执行，避免阻塞事件循环。

### 6.3 推理参数

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `device` | `cpu` | 可配置 `cuda`（可选） |
| `compute_type` | `int8` | CPU 量化 |
| `beam_size` | `1` | CPU 优先速度；可调大提升准确率 |
| `vad_filter` | `true` | 过滤静音 |
| `condition_on_previous_text` | `false` | 降低长音频重复/幻觉 |
| `language` | 请求参数 | `zh` / `en` / `auto` |
| `initial_prompt` | 中文时设置 | 提升中文标点与简繁稳定性 |

- `auto`：不传 `language`，读取 `info.language` 作为返回语言。
- 无语音：VAD 过滤后无 segment，返回空文本，`no_speech=true`。
- 结果文本去除首尾空白，合并 segment 时保留空格规则由模型输出决定。

### 6.4 离线策略

1. 安装阶段联网执行：
   ```bash
   python -m app.scripts.download_model
   ```
   下载到 `models/small/`。
2. 运行阶段：
   - 本地目录存在时只读本地文件。
   - 可设置 `HF_HUB_OFFLINE=1`、`ASR_OFFLINE=1` 强制离线。
3. 模型文件不纳入版本控制，`.gitignore` 排除 `models/`。

## 7. API 设计

### 7.1 路由

| Method | Path | 说明 |
| --- | --- | --- |
| GET | `/health` | 健康检查 |
| GET | `/api/status` | 模型与配置状态 |
| GET | `/v1/models` | 工具兼容：返回空模型列表（OpenCode vLLM 探测，不进 OpenAPI） |
| POST | `/api/transcribe` | 音频识别 |
| WS | `/ws/transcribe` | 实时识别 |
| GET | `/` | Web 页面 |
| GET | `/static/*` | 静态资源 |

### 7.2 `POST /api/transcribe` 处理顺序

1. 解析表单，校验 `language`、`source`。
2. 分块读取 `file`，超过 10 MB → 413。
3. 空文件 → 400。
4. `asyncio.to_thread(decode_audio)` 解码。
5. 录音来源校验 60 秒；可选配置校验总时长。
6. 静音快速返回。
7. `engine.ensure_loaded()`（失败 503）。
8. 计时开始，`asyncio.to_thread(engine.transcribe)`。
9. 组装响应，保留 3 位小数。
10. 捕获 `AppError` 原样返回；其他异常记录日志并返回 500。

`processing_seconds` 计时范围：解码开始前到推理结束，不含模型加载/下载。为了准确，解码单独计时后与推理耗时相加。

### 7.3 错误模型

- `AppError(status_code, code, message)` 由全局异常处理器转为：
  ```json
  { "detail": "message", "code": "code" }
  ```
- FastAPI 参数校验错误统一转为 422 `validation_error`，避免默认的错误结构不一致。
- 未捕获异常返回 500 `internal_error`，日志保留堆栈；推理异常单独映射为 `inference_failed`。

| code | HTTP | 场景 |
| --- | --- | --- |
| `empty_file` | 400 | 空文件 |
| `unsupported_audio` | 400 | 无法识别容器/无音频流 |
| `decode_failed` | 400 | 容器可识别但解码失败 |
| `invalid_language` | 400 | 语言不在允许集合 |
| `invalid_source` | 400 | source 非法 |
| `recording_too_long` | 400 | 录音超过 60 秒 |
| `audio_too_long` | 400 | 可选总时长限制触发 |
| `file_too_large` | 413 | 超过 10 MB |
| `validation_error` | 422 | 缺少 file 等参数错误 |
| `model_unavailable` | 503 | 模型加载失败/离线且未下载 |
| `inference_failed` | 500 | 推理异常 |
| `inference_timeout` | 504 | 推理超时（预留） |

### 7.4 健康检查与状态

- `/health` 固定返回 `{"status":"ok"}`，不等待模型，便于探活和测试。
- `/api/status` 返回模型名、设备、计算类型、是否已加载、离线开关、限制值和最近一次加载错误。
- 加载模型不阻塞服务启动；首次识别时懒加载。

### 7.5 工具探测兼容

OpenCode 内置 vLLM 本地发现会访问 `127.0.0.1:8000/health`，成功后再访问 `/v1/models`。本项目不是 LLM 服务，若不处理会在日志中产生周期性 404。设计取舍：

- 不伪造 LLM 能力，不实现 `/v1/chat/completions`；
- 只返回 `{"object":"list","data":[]}`，明确表示“没有聊天模型”；
- 路由设置 `include_in_schema=False`，不进入 API 文档；
- 该端点与业务流程完全解耦，失败也不影响识别。

## 8. 前端设计

### 8.1 页面结构

```text
Header: 标题 + 状态徽章 + 模型信息
┌─────────────────────────────────────────────────────┐
│ 识别语言：[中文] [English] [自动检测（实验）]          │
│ 模式：[麦克风录音] [上传音频]                          │
├───────────────────────┬─────────────────────────────┤
│ 录音卡片               │ 上传卡片                      │
│  ● 开始录音 / ■ 停止    │  [选择文件] [上传并识别]       │
│  00:00 / 60s 进度条     │  文件名 / 大小                 │
│  ☐ 实时识别（实验）     │                              │
├───────────────────────┴─────────────────────────────┤
│ 结果卡片                                              │
│ 语言 | 音频时长 | 处理耗时 | 模型                      │
│ [识别文本................................] [复制]      │
│ 实时预览（实时模式时显示）                             │
└─────────────────────────────────────────────────────┘
错误提示条 / 页脚说明
```

### 8.2 前端状态机

```text
idle
 ├─ 请求权限 → requesting
 │     ├─ 失败 → error → idle
 │     └─ 成功 → recording
 ├─ 选择文件 → file_selected
 └─ 上传识别 → processing

recording
 ├─ 点击停止 / 到达 60s → processing
 └─ 设备异常 → error → idle

processing
 ├─ 成功 → done → idle（保留结果）
 └─ 失败 → error → idle

实时模式：recording(ws) → finalizing → done
```

实现约定：

- 状态变化统一由 `setUiState(state, message)` 控制：按钮禁用、徽章颜色、状态文本、加载动画。
- 录音期间禁用语言切换、上传和再次录音。
- 识别期间显示已用时间；超过 3 秒追加“首次运行可能需要加载模型”的提示。
- 结果区保留到下一次识别开始；错误不清空上一次结果，便于对照。

### 8.3 录音实现

- `getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } })`。
- 选择 MIME：
  1. `audio/webm;codecs=opus`
  2. `audio/ogg;codecs=opus`
  3. `audio/mp4`
  4. 浏览器默认
- `MediaRecorder` 每 250 ms 收集一次 `dataavailable`；停止后组装 Blob。
- 计时器每 100 ms 更新；60 秒时自动调用停止逻辑，并标记 `autoStopped`。
- 停止后释放 `MediaStreamTrack`，避免麦克风指示灯常亮。
- 权限错误映射：
  - `NotAllowedError` → 权限被拒绝，请在地址栏允许麦克风。
  - `NotFoundError` / `DevicesNotFoundError` → 未检测到可用麦克风。
  - `NotReadableError` → 麦克风被其他程序占用。
  - 非安全上下文/无 `mediaDevices` → 请通过 `http://127.0.0.1:8000` 访问。

### 8.4 上传实现

- `accept=".wav,.webm,.ogg,.mp3,.m4a,audio/*"`。
- 选择时校验扩展名与 10 MB；不通过直接提示，不发请求。
- `FormData` 附加 `file`、`language`、`source=upload`。
- 使用 `fetch`，解析 JSON；失败时优先显示后端 `detail`，否则显示网络错误。
- 上传按钮在请求期间禁用，防止重复提交。

### 8.5 结果展示与复制

- 识别完成后显示 `text`、`language`、`duration_seconds`、`processing_seconds`、`model`。
- 文本为空时显示“未检测到可识别语音”，不显示为错误。
- 复制使用 `navigator.clipboard.writeText`；失败回退创建隐藏 `textarea` 并 `document.execCommand('copy')`。
- 复制成功按钮短暂变为“已复制”。

### 8.6 实时模式（F6）

采集：

1. `AudioContext`（默认采样率，通常 44.1/48 kHz）。
2. 加载 `pcm-worklet.js`，通过 `AudioWorkletNode` 获取单声道 `Float32` 帧。
3. 主线程线性插值降采样到 16 kHz，转 `Int16`。
4. 每约 250 ms 通过 WebSocket 发送一个二进制帧。
5. 节点接到 `GainNode(gain=0)` 再接 `destination`，保证处理链持续运行但不产生回声。

显示：

- `partial` 消息更新“实时预览”区域。
- 点击停止后发送 `{"type":"stop"}`，进入 `finalizing`，显示“正在生成最终结果…”。
- 收到 `final` 后用最终文本覆盖结果区；连接关闭。
- WebSocket 失败时提示错误，用户可取消实时勾选后使用普通录音。

## 9. 实时识别后端设计

### 9.1 会话缓冲

`RealtimeSession`：

- 保存累计 `float32` 样本（16 kHz 单声道）。
- 记录已处理位置 `processed_samples`。
- 每收到一个 PCM 分片：
  1. 转 `float32` 追加到缓冲。
  2. 累计时长超过 60 秒 → 返回错误 `recording_too_long`。
  3. 当新增样本 ≥ `REALTIME_CHUNK_SECONDS`（默认 2.5s）时，取“上次结束位置 - 0.4s 重叠”到当前末尾的片段进行识别。
  4. 将文本与累计文本合并去重，发送 `partial`。
- 停止时：
  1. 对完整缓冲做一次识别，作为最终文本。
  2. 发送 `final`，包含语言、时长、耗时。
  3. 关闭连接。

### 9.2 文本合并去重

分片边界可能切断词语，采用简单重叠合并：

1. 对累计文本尾部与新文本头部，寻找最长公共子串（最多 30 字符，最少 2 字符）。
2. 找到则去掉新文本的重复前缀。
3. 未找到则按语言拼接：中文直接连接，英文加空格。
4. 新文本为空则跳过。

该策略只影响临时展示，最终结果以整段识别为准。

### 9.3 并发与阻塞

- 每个 WebSocket 连接独立会话。
- 推理通过 `asyncio.to_thread` 执行，避免阻塞事件循环。
- 引擎内部锁保证同一时刻只有一个推理任务，多个连接会排队；本系统定位单用户，可接受。
- 接收循环与推理在同一协程中顺序执行；推理期间客户端分片由操作系统/WebSocket 缓冲，停止后仍能处理完剩余数据。

### 9.4 协议

客户端：

```json
{"type":"start","language":"zh"}
```

二进制：`Int16Array` 小端 PCM。

服务端：

```json
{"type":"ready","sample_rate":16000}
{"type":"partial","text":"累计文本","duration_seconds":3.2}
{"type":"final","text":"最终文本","language":"zh","duration_seconds":10.1,"processing_seconds":2.3}
{"type":"error","code":"inference_failed","message":"识别失败，请重试。"}
```

## 10. 配置项

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `ASR_MODEL` | `small` | faster-whisper 模型名或本地路径 |
| `ASR_DEVICE` | `cpu` | `cpu` / `cuda` |
| `ASR_COMPUTE_TYPE` | `int8` | CPU 量化类型 |
| `ASR_BEAM_SIZE` | `1` | 解码 beam 大小 |
| `ASR_MODEL_DIR` | `models` | 模型下载/存放目录 |
| `ASR_OFFLINE` | `0` | `1` 时只读本地模型 |
| `ASR_VAD_FILTER` | `1` | 是否启用 VAD |
| `MAX_UPLOAD_MB` | `10` | 上传大小上限 |
| `MAX_RECORDING_SECONDS` | `60` | 录音时长上限 |
| `MAX_AUDIO_SECONDS` | `0` | 上传音频总时长上限，0 为不限制 |
| `REALTIME_CHUNK_SECONDS` | `2.5` | 实时分片识别间隔 |
| `REALTIME_OVERLAP_SECONDS` | `0.4` | 实时分片重叠 |
| `ASR_LOG_LEVEL` | `INFO` | 日志级别 |

配置在进程启动时读取，测试可通过 `Settings` 直接构造覆盖。

## 11. 测试设计

### 11.1 默认测试（`python -m pytest -q`）

- 使用 `create_app(engine=FakeASREngine())`，不加载真实模型、不下载、不访问麦克风。
- `conftest.py` 生成临时 WAV（1 秒 440 Hz 正弦波，16 kHz/16-bit/单声道）。
- 覆盖：
  - `/health` 200。
  - `/api/status` 字段。
  - `/v1/models` 空模型兼容响应。
  - 中文/英文正常转写。
  - `auto` 语言。
  - 非法语言、非法 source、缺文件、空文件、损坏文件、非音频文件。
  - 超大文件（通过小限制 Settings 触发 413）。
  - 录音超 60 秒（生成 61 秒 WAV，或缩小限制）。
  - Fake 引擎抛 `ModelUnavailableError` → 503。
  - Fake 引擎抛普通异常 → 500。
  - 无语音 → 200 + 空文本 + `no_speech=true`。
  - 音频模块：WAV 解码、重采样、立体声、WebM/Opus 解码、时长、损坏字节。
  - 实时会话：分片合并、partial、final、超长、错误。
  - WebSocket：start → 二进制 → partial → stop → final。
  - 前后端流程：TestClient 上传示例 WAV 走完整 HTTP 链路。
- 当前基线：`49 passed, 3 skipped`（共 52 个用例）；跳过项为真实模型测试。

### 11.2 真实模型测试（单独执行）

```bash
python -m app.scripts.download_model
python -m pytest -q -m real_asr
```

- 标记 `@pytest.mark.real_asr`，默认由 `conftest.py` 跳过，除非设置 `RUN_REAL_ASR=1`。
- 使用 `samples/chinese.wav`、`samples/english.wav`。
- 断言识别文本包含参考文本中的关键词；记录实际文本与耗时。
- 不要求默认测试触发模型下载。

### 11.3 手工验收

- Chrome/Edge 实际录音、停止、识别、复制。
- 拒绝权限、无麦克风、上传空文件/损坏文件。
- 60 秒自动停止。
- 实时模式讲话时出现临时文本，停止后最终文本正确。
- 断网后（模型已下载）仍可识别。

## 12. 部署与运行

```bash
# 1. 创建 Python 3.12 虚拟环境（Windows 示例）
python3.12 -m venv .venv
.venv\Scripts\activate

# 2. 安装依赖
python -m pip install -r requirements.txt

# 3. 预下载模型（可选，首次识别也会自动下载）
python -m app.scripts.download_model

# 4. 启动
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

访问 `http://127.0.0.1:8000`。

离线验证：

```bash
set ASR_OFFLINE=1
set HF_HUB_OFFLINE=1
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

## 13. 性能与容量

- 模型：`small` int8 约 460 MB 内存占用（加载后更高，约 1 GB 级别）。
- 推理速度取决于 CPU；`beam_size=1` 优先速度。
- 上传限制 10 MB，避免一次性读入超大文件。
- 实时模式每 2.5 秒左右触发一次分片推理，单用户场景下 CPU 占用可控。
- 单进程、单模型、推理串行；不支持多用户并发吞吐，符合题目范围。
- 首次识别包含模型加载，页面会提示“首次运行可能较慢”。

## 14. 安全与隐私

- 仅监听 `127.0.0.1`，默认不暴露公网。
- 音频仅在内存处理，不落盘、不入库。
- 不使用用户文件名拼接路径，避免路径穿越。
- 分块读取并限制 10 MB，降低内存耗尽风险。
- 静态资源目录固定，不提供任意文件读取。
- 不接入任何第三方 ASR/统计/字体/CDN 服务。
- 日志不记录音频内容，仅记录时长、语言、耗时、错误类型。

## 15. 已知限制与后续演进

1. 实时模式为“分片重识别”，临时文本可能有抖动或边界错误；最终结果以整段识别为准。
2. CPU 推理速度受硬件影响，长音频处理时间线性增长。
3. 自动语言检测对短音频/混合语言可能不稳定，属于加分项。
4. 单模型实例串行推理，不适合多用户并发。
5. 未做降噪、说话人分离、标点后处理。
6. 后续可扩展：模型热切换、识别历史（需数据库）、流式原生模型、GPU 自动选择、Docker 部署（非当前约束）。

## 16. 设计决策记录

| 日期 | 决策 | 理由 |
| --- | --- | --- |
| 2026-11-19 | 采用 faster-whisper small + CPU int8 | 中英文均衡、免编译、CPU 可运行 |
| 2026-11-19 | 使用 PyAV 解码 | 不依赖系统 ffmpeg，覆盖浏览器录音格式 |
| 2026-11-19 | 上传仅限 10 MB，不设时长上限 | 符合需求；避免误拒正常文件 |
| 2026-11-19 | 录音 60 秒前端强制 + 后端 `source=recording` 校验 | 双重保障 |
| 2026-11-19 | 实时使用 WebSocket + 原始 PCM | 分片可独立处理，避免 WebM 分片解码问题 |
| 2026-11-19 | 默认懒加载模型 | 服务快速启动，`/health` 不受模型影响 |
| 2026-11-19 | 临时文本以整段最终识别覆盖 | 保证最终准确率，降低实时合并复杂度 |
| 2026-11-20 | `/v1/models` 返回空列表 | 兼容开发工具探测，避免 404；不伪造 LLM 能力 |
| 2026-11-20 | 录音/可选时长使用 0.5 s 容差 | 吸收编码补帧与重采样误差，前端仍按 60 s 主动停止 |
