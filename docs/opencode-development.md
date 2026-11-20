# OpenCode 开发过程记录

> 本文是项目开发期间与 OpenCode 协作的**关键会话与命令证据摘要**，用于说明 AI Programming 的实际过程，不是完整聊天记录。为可读性做了整理，技术结论、命令和输出均来自本机实际执行。

| 项目 | 内容 |
| --- | --- |
| 开发工具 | OpenCode CLI 2.3.2（VS Code 调用） |
| 开发日期 | 2026-11-19 至 2026-11-20 |
| 项目 | 本地语音识别 Web 系统（FastAPI + faster-whisper） |
| 运行环境 | Windows 11 x64、Python 3.12.13、Chrome 157、CPU |
| 证据来源 | 会话中的需求确认、文件读写、Shell 命令、测试与浏览器 E2E 输出 |
| 脱敏说明 | 已移除 API Key、HF Token、代理地址/端口、服务密码、用户名与本机绝对路径；模型与样例均为本地/合成数据 |

## 1. 记录方式

开发过程按三个阶段记录：

1. **需求理解与技术设计**：如何把原始需求拆成可实现、可验收的条目，并确定模型与架构。
2. **功能开发与集成**：如何实现后端 API、前端录音/上传、模型集成与实时模式。
3. **测试与问题修复**：如何用自动化测试、真实模型和浏览器 E2E 验证，并定位实际故障。

每条证据尽量包含：触发问题 → AI 分析/动作 → 实际命令或输出 → 开发者确认结果。

---

## 2. 阶段一：需求理解与技术设计

### 2.1 输入与约束

输入为项目根目录的 `项目需求文档.md`，核心约束：

- B/S 架构，浏览器录音/上传，后端本地识别。
- 中文 + 英文，不做翻译。
- Python 3.12、FastAPI、HTML/CSS/JS、pytest。
- CPU 可运行，不使用 Docker、Node.js、数据库、云端 ASR、系统 ffmpeg。
- 录音最长 60 秒，上传最大 10 MB。
- `GET /health`、`POST /api/transcribe`、`GET /` 为必做契约。
- 默认测试不得下载模型、不得依赖麦克风。

### 2.2 关键会话要点

> 以下为整理后的会话要点，非逐字转录。

| 主题 | OpenCode 的分析/动作 | 开发者确认的结论 | 落地位置 |
| --- | --- | --- | --- |
| 需求拆分 | 将原始需求拆为 F1 录音、F2 上传、F3 中英文识别、F4 展示、F5 异常、F6 实时 | 必做 F1–F5，F6 作为加分项实现 | `docs/requirements.md` |
| 模型选型 | 对比 faster-whisper base/small/medium、sherpa-onnx、FunASR、whisper.cpp | 采用 faster-whisper `small`，CPU `int8`，`beam_size=1` | `docs/design.md` 3.1 |
| 实时识别 | 分析 MediaRecorder 分片不可独立解码的问题 | 采用 WebSocket + 16 kHz 原始 PCM，分片重识别 | `docs/design.md` 9 |
| 样例音频 | 提出用 Windows 本地 TTS 生成中英文 WAV，避免版权与隐私问题 | 使用 Huihui/Zira 生成，附参考文本 | `scripts/generate_samples.ps1` |
| 上传时长 | 指出“10 MB 限制”和“时长限制”是两种不同约束 | 上传只限 10 MB，不设时长上限；录音仍限 60 秒 | `docs/requirements.md` 8.2 |
| 文档位置 | 建议正式文档统一存放，README 留在根目录 | 正式文档放 `docs/`，新增 OpenCode 过程记录 | `docs/` |
| 测试策略 | 建议默认注入 Fake 引擎，真实模型测试用环境变量隔离 | 默认 `pytest -q` 不下载模型；`RUN_REAL_ASR=1` 才跑真实测试 | `tests/conftest.py` |

### 2.3 模型选型证据

候选方案对比（节选）：

| 方案 | 结论 | 原因 |
| --- | --- | --- |
| faster-whisper small | **采用** | 中英文均衡、CPU int8 可用、pip 安装、自带 VAD |
| faster-whisper base | 备选 | 更快，但中文准确率下降 |
| faster-whisper medium | 不采用 | 普通 CPU 上过慢 |
| sherpa-onnx | 不采用 | 中英文常需两套模型，语言切换复杂 |
| FunASR / Paraformer | 不采用 | 中文强但英文弱、依赖重 |
| whisper.cpp | 不采用 | Windows Python 绑定/编译不稳定，违背免编译目标 |

实测（Intel Core Ultra 5 245K，CPU int8）：

```text
中文 samples/chinese.wav  8.685 s → 1.549 s
英文 samples/english.wav  7.125 s → 1.456 s
模型加载                  约 1.01 s（仅首次）
```

### 2.4 设计产出

- `docs/requirements.md`：F1–F6、接口契约、错误矩阵、假设与边界条件。
- `docs/design.md`：总体架构、模块职责、音频流水线、ASR 集成、实时协议、测试设计。
- 关键接口在实现前确定：
  - `POST /api/transcribe`：`file` + `language` + 可选 `source`。
  - 错误统一 `{ "detail": "...", "code": "..." }`。
  - WebSocket：`start` / 二进制 PCM / `stop` → `ready` / `partial` / `final` / `error`。

阶段一结果：需求、边界、模型和协议均在编码前固定，后续实现没有出现接口级返工。

---

## 3. 阶段二：功能开发与集成

### 3.1 实施顺序

| 顺序 | 模块 | 关键内容 | 验证 |
| --- | --- | --- | --- |
| 1 | 配置与错误 | `Settings`、`AppError`、错误码 | 单测导入 |
| 2 | 音频流水线 | 分块读取、PyAV 解码、WAV 兜底、重采样、静音 | `test_audio` |
| 3 | ASR 抽象 | `ASREngine`、`FakeASREngine`、`WhisperEngine` | Fake 单测 + 真实模型 |
| 4 | HTTP API | `/health`、`/api/status`、`/api/transcribe` | `TestClient` |
| 5 | 实时后端 | `RealtimeSession`、WebSocket 协议 | `test_realtime` |
| 6 | 前端 | 页面、状态机、录音、上传、复制、AudioWorklet | `node --check` + E2E |
| 7 | 样例与文档 | TTS 样例、README、设计/测试文档 | 人工验收 |

### 3.2 关键实现片段

音频解码统一输出 16 kHz 单声道 float32，并对 PyAV 版本差异做兼容：

```python
resampler = av.AudioResampler(format="s16", layout="mono", rate=TARGET_SAMPLE_RATE)
for frame in container.decode(stream):
    collect(resampler.resample(frame))
try:
    collect(resampler.resample(None))   # flush
except Exception:
    pass                                # 不同 PyAV 版本行为不同
```

模型懒加载，本地目录优先，离线时明确报 503：

```python
local_path = self._local_model_path()
if local_path is None and self.settings.offline:
    raise ModelUnavailableError(
        "模型尚未下载。请先联网执行 python -m app.scripts.download_model，"
        "或关闭 ASR_OFFLINE 后重试。"
    )
```

实时分片文本去重，避免重叠窗口产生重复：

```python
for size in range(max_overlap, 1, -1):
    if previous[-size:] == new[:size]:
        overlap = size
        break
if overlap:
    new = new[overlap:].lstrip()
```

### 3.3 依赖安装与模型初始化

依赖安装完成后确认版本：

```text
fastapi 0.165.0   uvicorn 0.54.0   faster-whisper 1.2.1
av 19.0.2         numpy 2.5.5      pytest 9.2.0
Python 3.12.13
```

首次模型下载先遇到镜像故障：

```text
Download failed: LocalEntryNotFoundError:
Got: HfHubHTTPError: Server error '500 Internal Server Error'
for url 'https://hf-mirror.com/api/models/Systran/faster-whisper-small/revision/main'
```

切换到官方端点并显式使用本机代理后成功：

```text
Downloading faster-whisper model: small
Target directory: <项目目录>/models/small
Model ready: <项目目录>/models/small
```

样例音频由 Windows TTS 生成并校验：

```text
chinese.wav 277,966 bytes → 8.685 s
english.wav 228,046 bytes → 7.125 s
```

### 3.4 集成验证

健康检查与状态（离线启动）：

```json
{"status":"ok"}
{"status":"ok","model":"small","device":"cpu","compute_type":"int8",
 "model_loaded":false,"model_ready":false,"offline":true,
 "max_upload_mb":10,"max_recording_seconds":60.0,"error":null}
```

真实 HTTP 识别：

```text
chinese.wav 200
text: 你好,欢迎使用本地语音识别系统。今天天气很好,适合在户外散步。
duration_seconds: 8.685   processing_seconds: 1.780

english.wav 200
text: Hello, welcome to the local speech recognition system. Today is a nice day for a walk outside.
duration_seconds: 7.125   processing_seconds: 1.434
```

实时 WebSocket：

```text
READY   {"type":"ready","sample_rate":16000,"language":"zh"}
PARTIAL 2.5  你好,欢迎使用本地语音。
PARTIAL 5.0  你好,欢迎使用本地语音。今天我们会用地语音识别系统。
FINAL   你好,欢迎使用本地语音识别系统。今天天气很好,适合在户外散步。
```

浏览器端到端（Chrome + 虚拟音频设备，真实点击按钮）：

```text
初始状态: 空闲
模型信息: small · cpu/int8 · 已就绪
点击开始: 录音中，计时器 00:01
点击停止: 识别中 → 已完成
识别结果: 你好,欢迎使用。
音频时长: 1.92 秒   处理耗时: 1.41 秒
```

阶段二结果：后端 API、前端录音/上传、模型集成和实时模式均完成，页面可走通完整 B/S 链路。

---

## 4. 阶段三：测试与问题修复

### 4.1 自动化测试

默认测试（不加载模型、不访问麦克风）：

```text
$ python -m pytest -q
49 passed, 3 skipped in 0.40s
```

真实模型测试：

```text
$ $env:RUN_REAL_ASR="1"; python -m pytest -q -m real_asr
3 passed, 49 deselected in 6.01s
```

真实识别输出：

```text
[chinese.wav] 你好,欢迎使用本地语音识别系统。今天天气很好,适合在户外散步。 (8.69s)
[english.wav] Hello, welcome to the local speech recognition system.
              Today is a nice day for a walk outside. (7.12s)
[HTTP] 你好,欢迎使用本地语音识别系统。今天天气很好,适合在户外散步。
```

测试数量随修复逐步增加：47 → 48（新增 WebM/Opus 回归）→ 49（新增工具探测兼容）。

### 4.2 浏览器 E2E 结果

| 场景 | 关键输出 | 结论 |
| --- | --- | --- |
| 普通录音 | 状态“录音中”→“已完成”，文本“你好,欢迎使用。”，1.92 s / 1.41 s | 通过 |
| 英文上传 | 文本正确，7.13 s / 1.50 s | 通过 |
| 中文上传 | 文本正确，8.69 s / 1.66 s | 通过 |
| 实时预览 | 预览“你好,欢迎使用本地语音。”，final 覆盖为完整文本，4.00 s / 1.44 s | 通过 |
| 复制 | 页面提示“已复制识别文本” | 通过 |
| 损坏文件 | 状态“出错”，提示支持 WAV/WebM/OGG/MP3/M4A，页面不崩溃 | 通过 |
| 权限拒绝 | 提示“麦克风权限被拒绝…”，开始按钮恢复 | 通过 |
| 60 秒上限 | 约 60.3 s 自动停止，计时 01:00，识别 59.94 s / 56.45 s | 通过 |

### 4.3 问题定位案例

#### 案例 A：PowerShell 中文脚本解析失败

- **现象**：执行样例生成脚本时报 `ParserError`，提示“字符串缺少终止符”。
- **定位**：Windows PowerShell 5.1 将无 BOM 的 UTF-8 中文脚本按本地代码页读取。
- **处理**：将 `scripts/generate_samples.ps1` 保存为 **UTF-8 with BOM** 后重试。
- **验证**：

```text
Generated chinese.wav (277,966 bytes)
Generated english.wav (228,046 bytes)
```

#### 案例 B：Hugging Face 镜像返回 500

- **现象**：模型下载失败，`hf-mirror.com` 返回 500。
- **定位**：镜像端点不可用，不是模型名或代码问题。
- **处理**：临时切换官方端点并配置本机代理；README 增加手动下载兜底说明。
- **验证**：`Model ready`，真实中英文测试 3 项通过。

#### 案例 C：日志中的 `GET /v1/models 404`

- **现象**：服务启动后日志周期性出现 `GET /v1/models 404`，但前端代码没有该请求。
- **定位**：临时中间件记录请求头，得到：

```text
/health    GET 200 ua='opencode/latest/2.3.2/cli'
/v1/models GET 404 ua='opencode/latest/2.3.2/cli'
```

进一步检查 OpenCode 安装文件，确认是其内置 vLLM 本地发现：先探测 `/health`，再读取 `/v1/models`，默认地址为 `http://127.0.0.1:8000`。

- **处理**：新增 `app/api/compat.py`，返回空模型列表；不实现聊天接口，不进入 OpenAPI。

```json
{"object":"list","data":[]}
```

- **验证**：同样请求头复测返回 200；默认测试新增 `test_vllm_discovery_sees_no_chat_models`，基线变为 49 passed。

#### 案例 D：其他边界问题

| 问题 | 定位 | 处理 |
| --- | --- | --- |
| PyAV flush 行为差异 | 不同版本 `resample(None)` 行为不同 | 兼容捕获 + 标准库 WAV 兜底 |
| 0.5 s 时长测试未触发 | 1 s 音频与 0.5 s 限制过于接近 | 明确 0.5 s 容差，测试改用 2 s 音频 |
| 中文拼接出现空格 | 按空格拼接 segment | 保留原始文本直接拼接 |
| 422 结构不一致 | FastAPI 默认校验错误 | 统一 `detail + code` 处理器 |
| 实时文本重复 | 分片重叠 | 最长后缀/前缀去重，最终整段覆盖 |
| 静音产生幻觉 | 无语音仍进入模型 | 峰值检测 + VAD 双重过滤 |

### 4.4 回归与验收

- `python -m pytest -q`：49 passed, 3 skipped。
- `RUN_REAL_ASR=1 pytest -m real_asr`：3 passed。
- 精确启动命令：`python -m uvicorn app.main:app --host 127.0.0.1 --port 8000`。
- `/health`、真实 HTTP 识别、浏览器录音/上传/实时/复制/异常/60 秒全部通过。
- 离线模式（`ASR_OFFLINE=1`、`HF_HUB_OFFLINE=1`）识别正常。
- 编译检查：`python -m compileall -q app tests`、`node --check static/js/app.js` 通过。

阶段三结果：测试失败与环境问题均形成“现象 → 定位 → 修复 → 回归”的闭环，最终基线稳定。

---

## 5. 关键证据索引

| 证据 | 位置 / 命令 | 结果 |
| --- | --- | --- |
| 需求与边界 | `docs/requirements.md` | F1–F6、假设、边界、错误矩阵 |
| 架构与选型 | `docs/design.md` | 模块职责、音频流水线、模型对比 |
| 默认测试 | `python -m pytest -q` | 49 passed, 3 skipped |
| 真实模型测试 | `RUN_REAL_ASR=1 pytest -m real_asr` | 3 passed，中英文文本正确 |
| 浏览器 E2E | Chrome + 虚拟音频 + CDP | 录音/上传/实时/复制/异常/60 s |
| 模型初始化 | `python -m app.scripts.download_model` | `Model ready` |
| 样例音频 | `scripts/generate_samples.ps1` | 8.685 s / 7.125 s |
| 端口探测定位 | 中间件记录请求头 | `ua='opencode/latest/2.3.2/cli'` |
| 完整测试记录 | `docs/test-report.md` | 用例矩阵、结果、已知问题 |
| AI 开发说明 | `docs/ai-development.md` | 任务、决策、问题、验收、改进 |

## 6. 脱敏与合规

- 已移除 API Key、HF Token、代理地址与端口、OpenCode 服务密码、用户名和本机绝对路径。
- 未提交完整历史对话、浏览器 Cookie、剪贴板内容或任何真实用户音频。
- 样例音频由 Windows 本地 TTS 合成，仅包含固定参考文本。
- 命令输出中的项目路径统一替换为 `<项目目录>`，不影响可复现性。

## 7. 结论

本记录展示了完整闭环：

1. **理解需求**：把自然语言需求拆成编号功能、边界与验收标准。
2. **技术设计**：对比模型与传输方案，先固定接口和错误契约。
3. **实现集成**：后端音频/ASR/API 与前端录音/上传/实时协同工作。
4. **测试修复**：用自动化测试、真实模型和浏览器 E2E 发现并修复实际问题。

AI 在其中承担了分析、生成、测试与定位的加速工作；关键决策、实际运行和最终验收由开发者完成。该过程可作为 AI Programming 能力的可复现证据。
