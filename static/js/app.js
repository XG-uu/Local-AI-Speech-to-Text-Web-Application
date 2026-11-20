(() => {
  "use strict";

  const LANGUAGE_LABELS = { zh: "中文", en: "English", auto: "自动检测" };
  const BADGE_LABELS = {
    idle: "空闲",
    requesting: "请求权限",
    recording: "录音中",
    processing: "识别中",
    finalizing: "生成最终结果",
    done: "已完成",
    error: "出错",
  };
  const SUPPORTED_EXTENSIONS = [".wav", ".webm", ".ogg", ".mp3", ".m4a", ".mp4", ".flac"];
  const RECORDING_MIME_TYPES = [
    "audio/webm;codecs=opus",
    "audio/ogg;codecs=opus",
    "audio/webm",
    "audio/mp4",
  ];
  const SILENT_AUDIO_MESSAGE = "没有采集到有效音频，请确认麦克风可用后重试。";

  const el = {
    statusBadge: document.getElementById("statusBadge"),
    modelInfo: document.getElementById("modelInfo"),
    recordTimer: document.getElementById("recordTimer"),
    timerLimit: document.getElementById("timerLimit"),
    recordLimitKicker: document.getElementById("recordLimitKicker"),
    uploadLimitKicker: document.getElementById("uploadLimitKicker"),
    recordProgressBar: document.getElementById("recordProgressBar"),
    recordProgress: document.getElementById("recordProgress"),
    startBtn: document.getElementById("startBtn"),
    stopBtn: document.getElementById("stopBtn"),
    realtimeToggle: document.getElementById("realtimeToggle"),
    recordHint: document.getElementById("recordHint"),
    dropZone: document.getElementById("dropZone"),
    fileInput: document.getElementById("fileInput"),
    fileMeta: document.getElementById("fileMeta"),
    uploadBtn: document.getElementById("uploadBtn"),
    uploadHint: document.getElementById("uploadHint"),
    copyBtn: document.getElementById("copyBtn"),
    currentLanguageLabel: document.getElementById("currentLanguageLabel"),
    resultLanguage: document.getElementById("resultLanguage"),
    resultDuration: document.getElementById("resultDuration"),
    resultProcessing: document.getElementById("resultProcessing"),
    resultModel: document.getElementById("resultModel"),
    realtimePreviewWrap: document.getElementById("realtimePreviewWrap"),
    realtimePreview: document.getElementById("realtimePreview"),
    resultText: document.getElementById("resultText"),
    emptyHint: document.getElementById("emptyHint"),
    errorBanner: document.getElementById("errorBanner"),
    errorText: document.getElementById("errorText"),
    dismissError: document.getElementById("dismissError"),
    toast: document.getElementById("toast"),
  };

  const state = {
    language: readStoredLanguage(),
    mode: "idle",
    stream: null,
    mediaRecorder: null,
    chunks: [],
    timerId: null,
    recordingStartedAt: 0,
    autoStopped: false,
    realtimeActive: false,
    ws: null,
    audioContext: null,
    sourceNode: null,
    workletNode: null,
    gainNode: null,
    pcmQueue: [],
    pcmQueuedSamples: 0,
    realtimeText: "",
    finalReceived: false,
    selectedFile: null,
    maxRecordingSeconds: 60,
    maxUploadMb: 10,
    maxUploadBytes: 10 * 1024 * 1024,
    modelName: "—",
    processingTicker: null,
    toastTimer: null,
  };

  function readStoredLanguage() {
    try {
      const stored = localStorage.getItem("asr.language");
      return stored && LANGUAGE_LABELS[stored] ? stored : "zh";
    } catch (_error) {
      return "zh";
    }
  }

  function storeLanguage(language) {
    try {
      localStorage.setItem("asr.language", language);
    } catch (_error) {
      /* localStorage may be disabled; the in-memory choice still works. */
    }
  }

  function isBusy() {
    return ["requesting", "recording", "processing", "finalizing"].includes(state.mode);
  }

  function setLanguage(language, persist = true) {
    if (!LANGUAGE_LABELS[language]) return;
    state.language = language;
    document.querySelectorAll(".segment").forEach((button) => {
      button.setAttribute("aria-pressed", String(button.dataset.language === language));
    });
    el.currentLanguageLabel.textContent = `当前语言：${LANGUAGE_LABELS[language]}`;
    if (persist) storeLanguage(language);
  }

  function setUiState(mode, message) {
    state.mode = mode;
    el.statusBadge.className = `badge badge-${mode}`;
    el.statusBadge.textContent = BADGE_LABELS[mode] || mode;

    const busy = isBusy();
    el.startBtn.disabled = busy;
    el.stopBtn.disabled = mode !== "recording";
    el.uploadBtn.disabled = busy || !state.selectedFile;
    el.fileInput.disabled = busy;
    el.realtimeToggle.disabled = busy;
    document.querySelectorAll(".segment").forEach((button) => {
      button.disabled = busy;
    });
    el.recordProgress.classList.toggle("is-recording", mode === "recording");

    if (mode === "processing" || mode === "finalizing") {
      el.uploadBtn.textContent = "识别中…";
      startProcessingTicker(message || "正在识别，请稍候…");
    } else {
      stopProcessingTicker();
      el.uploadBtn.textContent = "上传并识别";
      if (message) {
        el.recordHint.textContent = message;
        el.uploadHint.textContent = message;
      }
      if (mode === "idle") {
        el.uploadHint.textContent = "上传文件不会保存到磁盘，仅在本机内存中处理。";
      }
    }

    if (mode === "recording") {
      el.recordHint.textContent = message || "正在录音，点击停止后识别。";
      el.uploadHint.textContent = "录音期间暂不可上传，停止后可继续使用。";
    }
    if (mode === "done" || mode === "error" || mode === "idle") {
      el.recordProgress.classList.remove("is-recording");
    }
  }

  function startProcessingTicker(baseMessage) {
    stopProcessingTicker();
    const started = performance.now();
    const base = String(baseMessage || "正在识别，请稍候…").replace(/[。.!！]+$/, "");
    state.processingTicker = window.setInterval(() => {
      const seconds = Math.floor((performance.now() - started) / 1000);
      let text = `${base} 已等待 ${seconds} 秒`;
      if (seconds >= 3) {
        text += "。首次识别需要加载本地模型，可能稍慢。";
      }
      el.recordHint.textContent = text;
      el.uploadHint.textContent = text;
    }, 500);
  }

  function stopProcessingTicker() {
    if (state.processingTicker !== null) {
      window.clearInterval(state.processingTicker);
      state.processingTicker = null;
    }
  }

  function startTimer() {
    stopTimer();
    state.recordingStartedAt = performance.now();
    updateTimer();
    state.timerId = window.setInterval(updateTimer, 100);
  }

  function updateTimer() {
    if (state.mode !== "recording") return;
    const elapsed = Math.min(
      (performance.now() - state.recordingStartedAt) / 1000,
      state.maxRecordingSeconds,
    );
    el.recordTimer.textContent = formatClock(elapsed);
    const percent = Math.min(100, (elapsed / state.maxRecordingSeconds) * 100);
    el.recordProgress.style.width = `${percent}%`;
    el.recordProgressBar.setAttribute("aria-valuenow", String(Math.round(elapsed)));
    if (elapsed >= state.maxRecordingSeconds) {
      stopRecording(true);
    }
  }

  function stopTimer() {
    if (state.timerId !== null) {
      window.clearInterval(state.timerId);
      state.timerId = null;
    }
  }

  function resetTimerDisplay() {
    el.recordTimer.textContent = "00:00";
    el.recordProgress.style.width = "0%";
    el.recordProgressBar.setAttribute("aria-valuenow", "0");
  }

  function pickRecordingMime() {
    if (typeof MediaRecorder === "undefined" || typeof MediaRecorder.isTypeSupported !== "function") {
      return "";
    }
    return RECORDING_MIME_TYPES.find((type) => MediaRecorder.isTypeSupported(type)) || "";
  }

  function mimeToExtension(mime) {
    const value = (mime || "").toLowerCase();
    if (value.includes("ogg")) return "ogg";
    if (value.includes("mp4") || value.includes("m4a")) return "m4a";
    if (value.includes("wav")) return "wav";
    return "webm";
  }

  function mediaErrorMessage(error) {
    if (error && error.name === "NotAllowedError") {
      return "麦克风权限被拒绝。请点击地址栏旁的麦克风图标，允许本页面使用麦克风后重试。";
    }
    if (error && (error.name === "NotFoundError" || error.name === "DevicesNotFoundError")) {
      return "未检测到可用麦克风，请连接麦克风设备后重试。";
    }
    if (error && error.name === "NotReadableError") {
      return "麦克风被其他程序占用或无法读取，请关闭占用麦克风的程序后重试。";
    }
    if (error && error.name === "OverconstrainedError") {
      return "当前麦克风不支持请求的音频参数，请更换设备后重试。";
    }
    return (error && error.message) || "无法启动录音，请检查麦克风与浏览器权限后重试。";
  }

  async function startRecording() {
    if (isBusy()) return;
    clearError();
    state.autoStopped = false;
    state.finalReceived = false;
    state.realtimeText = "";
    state.realtimeActive = el.realtimeToggle.checked;
    el.realtimePreviewWrap.hidden = !state.realtimeActive;
    el.realtimePreview.textContent = "等待语音…";
    resetTimerDisplay();
    setUiState("requesting", "正在请求麦克风权限…");

    try {
      if (!navigator.mediaDevices || typeof navigator.mediaDevices.getUserMedia !== "function") {
        throw new Error(
          "当前浏览器不支持麦克风采集。请使用最新版 Chrome 或 Edge，并通过 http://127.0.0.1:8000 访问。",
        );
      }
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      state.stream = stream;

      if (state.realtimeActive) {
        await startRealtime(stream);
      } else {
        startMediaRecorder(stream);
      }

      setUiState(
        "recording",
        state.realtimeActive ? "正在实时识别，请讲话…" : "正在录音，点击“停止录音”后开始识别。",
      );
      startTimer();
    } catch (error) {
      cleanupAllMedia();
      const message = mediaErrorMessage(error);
      showError(message);
      setUiState("error", message);
    }
  }

  function startMediaRecorder(stream) {
    const mimeType = pickRecordingMime();
    const options = mimeType ? { mimeType, audioBitsPerSecond: 128000 } : undefined;
    let recorder;
    try {
      recorder = options ? new MediaRecorder(stream, options) : new MediaRecorder(stream);
    } catch (error) {
      throw new Error("当前浏览器无法创建录音器，请使用最新版 Chrome 或 Edge。");
    }

    state.mediaRecorder = recorder;
    state.chunks = [];

    recorder.ondataavailable = (event) => {
      if (event.data && event.data.size > 0) {
        state.chunks.push(event.data);
      }
    };

    recorder.onerror = () => {
      cleanupAllMedia();
      showError("录音过程中发生错误，请检查麦克风后重试。");
      setUiState("error", "录音失败");
    };

    recorder.onstop = () => {
      const type = recorder.mimeType || mimeType || "audio/webm";
      const blob = new Blob(state.chunks, { type });
      state.chunks = [];
      recorder.ondataavailable = null;
      recorder.onerror = null;
      recorder.onstop = null;
      state.mediaRecorder = null;
      stopStream();

      if (!blob.size) {
        showError(SILENT_AUDIO_MESSAGE);
        setUiState("error", "没有录到音频");
        return;
      }
      transcribeBlob(blob, `recording.${mimeToExtension(type)}`, "recording");
    };

    recorder.start(250);
  }

  function stopRecording(auto = false) {
    if (state.mode !== "recording") return;
    stopTimer();
    state.autoStopped = auto;

    if (state.realtimeActive) {
      stopRealtime(auto);
      return;
    }

    setUiState(
      "processing",
      auto ? "已达到 60 秒上限，正在识别录音…" : "正在识别录音，请稍候…",
    );

    if (state.mediaRecorder && state.mediaRecorder.state !== "inactive") {
      try {
        state.mediaRecorder.stop();
      } catch (_error) {
        cleanupAllMedia();
        showError("停止录音失败，请重试。");
        setUiState("error", "停止录音失败");
      }
    } else {
      cleanupAllMedia();
      showError("录音尚未正确开始，请重试。");
      setUiState("error", "录音失败");
    }
  }

  async function startRealtime(stream) {
    const protocol = window.location.protocol === "https:" ? "wss" : "ws";
    const url = `${protocol}://${window.location.host}/ws/transcribe?language=${encodeURIComponent(state.language)}`;
    const ws = new WebSocket(url);
    state.ws = ws;

    await new Promise((resolve, reject) => {
      let settled = false;
      const timeout = window.setTimeout(() => {
        if (!settled) {
          settled = true;
          reject(new Error("实时识别连接超时，请切回普通录音后重试。"));
        }
      }, 10000);

      const finish = (error) => {
        if (settled) return;
        settled = true;
        window.clearTimeout(timeout);
        if (error) reject(error);
        else resolve();
      };

      ws.onopen = () => {
        ws.send(JSON.stringify({ type: "start", language: state.language }));
      };

      ws.onmessage = (event) => {
        let data;
        try {
          data = JSON.parse(event.data);
        } catch (_error) {
          return;
        }
        if (data.type === "ready") {
          finish();
        } else if (data.type === "partial") {
          updateRealtimePreview(data.text);
        } else if (data.type === "final") {
          handleRealtimeFinal(data);
        } else if (data.type === "error") {
          if (!settled) {
            finish(new Error(data.message || "实时识别启动失败。"));
          } else {
            handleRealtimeError(data.message || "实时识别失败，请重试。");
          }
        }
      };

      ws.onerror = () => {
        if (!settled) {
          finish(new Error("无法连接实时识别服务，请切回普通录音后重试。"));
        }
      };

      ws.onclose = () => {
        if (!settled) {
          finish(new Error("实时识别连接已关闭，请切回普通录音后重试。"));
        } else if (
          !state.finalReceived &&
          (state.mode === "recording" || state.mode === "finalizing")
        ) {
          handleRealtimeError("实时识别连接已断开，请重试或改用普通录音。");
        }
      };
    });

    await setupRealtimeAudio(stream);
  }

  async function setupRealtimeAudio(stream) {
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextClass) {
      throw new Error("当前浏览器不支持 Web Audio，请使用最新版 Chrome 或 Edge。");
    }

    const context = new AudioContextClass();
    state.audioContext = context;
    if (context.state === "suspended") {
      await context.resume();
    }
    if (!context.audioWorklet) {
      throw new Error("当前浏览器不支持 AudioWorklet，请取消勾选实时识别后重试。");
    }

    await context.audioWorklet.addModule("/static/js/pcm-worklet.js");
    const source = context.createMediaStreamSource(stream);
    const node = new AudioWorkletNode(context, "pcm-capture", {
      numberOfInputs: 1,
      numberOfOutputs: 1,
      outputChannelCount: [1],
    });
    const gain = context.createGain();
    gain.gain.value = 0;
    source.connect(node);
    node.connect(gain);
    gain.connect(context.destination);

    state.sourceNode = source;
    state.workletNode = node;
    state.gainNode = gain;
    state.pcmQueue = [];
    state.pcmQueuedSamples = 0;

    node.port.onmessage = (event) => {
      if (!state.realtimeActive) return;
      const input = event.data;
      if (!input || !input.length) return;
      const downsampled = downsample(input, context.sampleRate, 16000);
      state.pcmQueue.push(downsampled);
      state.pcmQueuedSamples += downsampled.length;
      if (state.pcmQueuedSamples >= 4000) {
        flushPcm();
      }
    };
  }

  function downsample(input, inputRate, outputRate = 16000) {
    if (!inputRate || inputRate === outputRate) return input;
    const ratio = inputRate / outputRate;
    const length = Math.max(1, Math.round(input.length / ratio));
    const output = new Float32Array(length);
    for (let i = 0; i < length; i += 1) {
      const position = i * ratio;
      const lower = Math.floor(position);
      const upper = Math.min(lower + 1, input.length - 1);
      const weight = position - lower;
      output[i] = input[lower] * (1 - weight) + input[upper] * weight;
    }
    return output;
  }

  function flushPcm() {
    if (!state.pcmQueuedSamples) return;
    const merged = new Float32Array(state.pcmQueuedSamples);
    let offset = 0;
    state.pcmQueue.forEach((chunk) => {
      merged.set(chunk, offset);
      offset += chunk.length;
    });
    state.pcmQueue = [];
    state.pcmQueuedSamples = 0;

    const pcm = new Int16Array(merged.length);
    for (let i = 0; i < merged.length; i += 1) {
      const sample = Math.max(-1, Math.min(1, merged[i]));
      pcm[i] = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
    }

    if (state.ws && state.ws.readyState === WebSocket.OPEN) {
      state.ws.send(pcm.buffer);
    }
  }

  function stopRealtime(auto) {
    if (!state.ws || state.ws.readyState !== WebSocket.OPEN) {
      handleRealtimeError("实时识别连接不可用，请改用普通录音后重试。");
      return;
    }

    flushPcm();
    setUiState(
      "finalizing",
      auto ? "已达到 60 秒上限，正在生成最终结果…" : "正在生成最终结果…",
    );
    cleanupRealtimeAudio();
    stopStream();

    try {
      state.ws.send(JSON.stringify({ type: "stop" }));
    } catch (_error) {
      handleRealtimeError("提交实时识别失败，请改用普通录音后重试。");
    }
  }

  function updateRealtimePreview(text) {
    state.realtimeText = text || "";
    el.realtimePreviewWrap.hidden = false;
    el.realtimePreview.textContent = state.realtimeText || "等待语音…";
  }

  function handleRealtimeFinal(data) {
    state.finalReceived = true;
    cleanupRealtimeAudio();
    stopStream();
    closeRealtimeSocket();

    renderResult({
      ...data,
      model: data.model || state.modelName,
    });
    updateRealtimePreview(data.text || "（未检测到可识别语音）");
    setUiState("done", data.no_speech ? "未检测到可识别语音" : "识别完成");
  }

  function handleRealtimeError(message) {
    cleanupAllMedia();
    showError(message);
    setUiState("error", message);
  }

  function cleanupRealtimeAudio() {
    if (state.workletNode) {
      try {
        state.workletNode.port.onmessage = null;
        state.workletNode.disconnect();
      } catch (_error) {
        /* already disconnected */
      }
      state.workletNode = null;
    }
    if (state.sourceNode) {
      try {
        state.sourceNode.disconnect();
      } catch (_error) {
        /* already disconnected */
      }
      state.sourceNode = null;
    }
    if (state.gainNode) {
      try {
        state.gainNode.disconnect();
      } catch (_error) {
        /* already disconnected */
      }
      state.gainNode = null;
    }
    if (state.audioContext) {
      state.audioContext.close().catch(() => {});
      state.audioContext = null;
    }
    state.pcmQueue = [];
    state.pcmQueuedSamples = 0;
  }

  function closeRealtimeSocket() {
    const ws = state.ws;
    state.ws = null;
    if (!ws) return;
    ws.onmessage = null;
    ws.onerror = null;
    ws.onclose = null;
    try {
      if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) {
        ws.close();
      }
    } catch (_error) {
      /* socket already closed */
    }
  }

  function stopStream() {
    if (state.stream) {
      state.stream.getTracks().forEach((track) => track.stop());
      state.stream = null;
    }
  }

  function cleanupAllMedia() {
    stopTimer();
    cleanupRealtimeAudio();
    closeRealtimeSocket();
    if (state.mediaRecorder) {
      const recorder = state.mediaRecorder;
      recorder.ondataavailable = null;
      recorder.onerror = null;
      recorder.onstop = null;
      if (recorder.state !== "inactive") {
        try {
          recorder.stop();
        } catch (_error) {
          /* recorder already stopped */
        }
      }
      state.mediaRecorder = null;
    }
    state.chunks = [];
    state.realtimeActive = false;
    stopStream();
  }

  async function transcribeBlob(blob, filename, source) {
    if (!blob || !blob.size) {
      showError(SILENT_AUDIO_MESSAGE);
      setUiState("error", "没有可识别的音频");
      return;
    }

    const form = new FormData();
    form.append("file", blob, filename);
    form.append("language", state.language);
    form.append("source", source);

    setUiState(
      "processing",
      source === "recording"
        ? state.autoStopped
          ? "已达到 60 秒上限，正在识别录音…"
          : "正在识别录音，请稍候…"
        : "正在识别上传文件，请稍候…",
    );

    try {
      const data = await fetchJson("/api/transcribe", { method: "POST", body: form });
      renderResult(data);
      setUiState("done", data.no_speech ? "未检测到可识别语音" : "识别完成");
    } catch (error) {
      showError(error.message || "识别失败，请重试。");
      setUiState("error", "识别失败，请重试");
    }
  }

  async function fetchJson(url, options) {
    let response;
    try {
      response = await fetch(url, options);
    } catch (_error) {
      throw new Error("无法连接本地识别服务，请确认后端已启动。");
    }

    let data = {};
    try {
      data = await response.json();
    } catch (_error) {
      data = {};
    }

    if (!response.ok) {
      const message = data.detail || data.message || `请求失败（HTTP ${response.status}）`;
      throw new Error(message);
    }
    return data;
  }

  function renderResult(data) {
    const text = (data.text || "").trim();
    el.resultText.value = text;
    el.emptyHint.hidden = text.length > 0;
    el.copyBtn.disabled = !text;

    const detected = LANGUAGE_LABELS[data.language] || data.language || "—";
    el.resultLanguage.textContent =
      data.requested_language === "auto" ? `${detected}（自动检测）` : detected;
    el.resultDuration.textContent = formatSeconds(data.duration_seconds);
    el.resultProcessing.textContent = formatSeconds(data.processing_seconds);
    el.resultModel.textContent = data.model || state.modelName || "—";
  }

  function formatSeconds(value) {
    const number = Number(value);
    if (!Number.isFinite(number)) return "—";
    return `${number.toFixed(2)} 秒`;
  }

  function formatClock(seconds) {
    const total = Math.max(0, Math.floor(seconds));
    const minutes = String(Math.floor(total / 60)).padStart(2, "0");
    const remainder = String(total % 60).padStart(2, "0");
    return `${minutes}:${remainder}`;
  }

  function formatBytes(bytes) {
    if (!Number.isFinite(bytes) || bytes < 0) return "—";
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
  }

  function validateFile(file) {
    if (!file) {
      return "请选择音频文件。";
    }
    if (file.size === 0) {
      return "所选文件为空，请选择包含语音的音频文件。";
    }
    if (file.size > state.maxUploadBytes) {
      return `文件大小 ${formatBytes(file.size)} 超过 ${state.maxUploadMb} MB 上限，请压缩或裁剪后重试。`;
    }
    const name = file.name || "";
    const dot = name.lastIndexOf(".");
    const extension = dot >= 0 ? name.slice(dot).toLowerCase() : "";
    const typeOk = (file.type || "").startsWith("audio/") || SUPPORTED_EXTENSIONS.includes(extension);
    if (!typeOk) {
      return "不支持该文件类型，请上传 WAV、WebM、OGG、MP3 或 M4A 音频。";
    }
    return "";
  }

  function setSelectedFile(file) {
    const error = validateFile(file);
    if (error) {
      state.selectedFile = null;
      el.fileMeta.textContent = "尚未选择文件";
      el.fileMeta.classList.remove("has-file");
      el.uploadBtn.disabled = true;
      showError(error);
      return;
    }

    state.selectedFile = file;
    el.fileMeta.textContent = `${file.name} · ${formatBytes(file.size)}`;
    el.fileMeta.classList.add("has-file");
    el.uploadBtn.disabled = isBusy();
    clearError();
  }

  async function uploadSelectedFile() {
    if (!state.selectedFile || isBusy()) return;
    await transcribeBlob(state.selectedFile, state.selectedFile.name, "upload");
  }

  function showError(message) {
    el.errorText.textContent = message;
    el.errorBanner.hidden = false;
  }

  function clearError() {
    el.errorBanner.hidden = true;
    el.errorText.textContent = "";
  }

  function showToast(message) {
    el.toast.textContent = message;
    el.toast.hidden = false;
    if (state.toastTimer !== null) {
      window.clearTimeout(state.toastTimer);
    }
    state.toastTimer = window.setTimeout(() => {
      el.toast.hidden = true;
      state.toastTimer = null;
    }, 1800);
  }

  async function copyResult() {
    const text = el.resultText.value.trim();
    if (!text) return;
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(text);
      } else {
        fallbackCopy(text);
      }
      showToast("已复制识别文本");
    } catch (_error) {
      try {
        fallbackCopy(text);
        showToast("已复制识别文本");
      } catch (_fallbackError) {
        showError("复制失败，请手动选择文本后复制。");
      }
    }
  }

  function fallbackCopy(text) {
    const textarea = document.createElement("textarea");
    textarea.value = text;
    textarea.setAttribute("readonly", "");
    textarea.style.position = "fixed";
    textarea.style.left = "-9999px";
    document.body.appendChild(textarea);
    textarea.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(textarea);
    if (!ok) throw new Error("execCommand copy failed");
  }

  async function loadStatus() {
    try {
      const status = await fetchJson("/api/status");
      state.maxRecordingSeconds = Number(status.max_recording_seconds) || 60;
      state.maxUploadMb = Number(status.max_upload_mb) || 10;
      state.maxUploadBytes = state.maxUploadMb * 1024 * 1024;
      state.modelName = status.model || "—";

      const readyText = status.model_ready ? "已就绪" : "首次识别时加载";
      let modelText = `模型：${state.modelName} · ${status.device || "cpu"}/${status.compute_type || "int8"} · ${readyText}`;
      if (status.error) {
        modelText += ` · ${status.error}`;
      }
      el.modelInfo.textContent = modelText;
      el.timerLimit.textContent = `/ ${formatClock(state.maxRecordingSeconds)}`;
      el.recordLimitKicker.textContent = `最长 ${Math.round(state.maxRecordingSeconds)} 秒`;
      el.uploadLimitKicker.textContent = `最大 ${state.maxUploadMb} MB`;
      el.recordProgressBar.setAttribute("aria-valuemax", String(state.maxRecordingSeconds));
    } catch (_error) {
      el.modelInfo.textContent = "模型状态未知（请确认后端服务已启动）";
    }
  }

  document.querySelectorAll(".segment").forEach((button) => {
    button.addEventListener("click", () => setLanguage(button.dataset.language));
  });

  el.startBtn.addEventListener("click", startRecording);
  el.stopBtn.addEventListener("click", () => stopRecording(false));
  el.uploadBtn.addEventListener("click", uploadSelectedFile);
  el.copyBtn.addEventListener("click", copyResult);
  el.dismissError.addEventListener("click", clearError);

  el.fileInput.addEventListener("change", () => {
    const file = el.fileInput.files && el.fileInput.files[0];
    setSelectedFile(file || null);
    el.fileInput.value = "";
  });

  el.dropZone.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      el.fileInput.click();
    }
  });

  ["dragenter", "dragover"].forEach((name) => {
    el.dropZone.addEventListener(name, (event) => {
      event.preventDefault();
      el.dropZone.classList.add("is-dragover");
    });
  });

  ["dragleave", "dragend"].forEach((name) => {
    el.dropZone.addEventListener(name, () => {
      el.dropZone.classList.remove("is-dragover");
    });
  });

  el.dropZone.addEventListener("drop", (event) => {
    event.preventDefault();
    el.dropZone.classList.remove("is-dragover");
    if (isBusy()) return;
    const file = event.dataTransfer && event.dataTransfer.files && event.dataTransfer.files[0];
    if (file) setSelectedFile(file);
  });

  el.realtimeToggle.addEventListener("change", () => {
    el.recordHint.textContent = el.realtimeToggle.checked
      ? "实时模式：录音过程中会持续显示临时文本，停止后生成最终结果。"
      : "点击开始录音，浏览器会请求麦克风权限。";
  });

  window.addEventListener("beforeunload", () => {
    cleanupAllMedia();
  });

  setLanguage(state.language, false);
  resetTimerDisplay();
  setUiState("idle", "点击开始录音，浏览器会请求麦克风权限。");
  loadStatus();
})();
