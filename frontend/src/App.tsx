import { Mic, Square, Volume2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { buildWsUrl, requestTts } from "./api";
import { startPcmRecorder, type RecorderHandle } from "./audio";
import type { LanguageCode, ServerEvent, StreamConfig } from "./types";
import "./styles.css";

const languageLabels: Record<LanguageCode, string> = {
  zh: "中文",
  ja: "日本語",
  en: "English",
};

const presets: Array<{ label: string; source: LanguageCode; target: LanguageCode }> = [
  { label: "中 → 日", source: "zh", target: "ja" },
  { label: "日 → 中", source: "ja", target: "zh" },
  { label: "英 → 日", source: "en", target: "ja" },
  { label: "日 → 英", source: "ja", target: "en" },
];

export default function App() {
  const [sourceLanguage, setSourceLanguage] = useState<LanguageCode>("zh");
  const [targetLanguage, setTargetLanguage] = useState<LanguageCode>("ja");
  const [enableTts, setEnableTts] = useState(false);
  const [status, setStatus] = useState("未连接");
  const [transcript, setTranscript] = useState("");
  const [translation, setTranslation] = useState("");
  const [finalTranslation, setFinalTranslation] = useState("");
  const [error, setError] = useState("");
  const [isRecording, setIsRecording] = useState(false);

  const wsRef = useRef<WebSocket | null>(null);
  const recorderRef = useRef<RecorderHandle | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  useEffect(() => {
    return () => {
      void stop();
    };
  }, []);

  async function playTts(text: string) {
    if (!text.trim()) {
      return;
    }
    const blob = await requestTts(text, targetLanguage);
    const url = URL.createObjectURL(blob);
    if (audioRef.current) {
      audioRef.current.pause();
    }
    const audio = new Audio(url);
    audioRef.current = audio;
    audio.onended = () => URL.revokeObjectURL(url);
    await audio.play();
  }

  function handleServerEvent(event: ServerEvent) {
    if (event.type === "ready") {
      setStatus("已连接，正在监听");
    } else if (event.type === "speech.started") {
      setStatus("检测到语音");
    } else if (event.type === "speech.stopped") {
      setStatus("语音片段处理中");
    } else if (event.type === "transcript.delta" || event.type === "transcript.done") {
      setTranscript(event.text);
    } else if (event.type === "translation.reset") {
      setTranslation("");
    } else if (event.type === "translation.delta") {
      setTranslation(event.text);
    } else if (event.type === "translation.done") {
      setTranslation(event.text);
      if (event.is_final) {
        setFinalTranslation(event.text);
        if (enableTts) {
          void playTts(event.text).catch((err: unknown) => {
            setError(err instanceof Error ? err.message : String(err));
          });
        }
      }
    } else if (event.type === "warning") {
      setStatus(event.message);
    } else if (event.type === "error") {
      setError(event.message);
      setStatus("出错");
    }
  }

  async function start() {
    setError("");
    setTranscript("");
    setTranslation("");
    setFinalTranslation("");
    setStatus("正在连接后端");

    const ws = new WebSocket(buildWsUrl());
    wsRef.current = ws;

    const config: StreamConfig = {
      source_language: sourceLanguage,
      target_language: targetLanguage,
      enable_tts: enableTts,
    };

    await new Promise<void>((resolve, reject) => {
      ws.onopen = () => {
        ws.send(JSON.stringify({ type: "start", config }));
        resolve();
      };
      ws.onerror = () => reject(new Error("WebSocket 连接失败"));
    });

    ws.onmessage = (message) => {
      const event = JSON.parse(message.data) as ServerEvent;
      handleServerEvent(event);
    };
    ws.onclose = () => {
      setIsRecording(false);
      setStatus("连接已关闭");
    };

    const recorder = await startPcmRecorder((chunk) => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "audio", audio: chunk }));
      }
    });
    recorderRef.current = recorder;
    setIsRecording(true);
  }

  async function stop() {
    if (recorderRef.current) {
      await recorderRef.current.stop();
      recorderRef.current = null;
    }
    if (wsRef.current) {
      if (wsRef.current.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({ type: "stop" }));
      }
      wsRef.current.close();
      wsRef.current = null;
    }
    setIsRecording(false);
    setStatus("已停止");
  }

  function applyPreset(source: LanguageCode, target: LanguageCode) {
    setSourceLanguage(source);
    setTargetLanguage(target);
  }

  return (
    <main className="appShell">
      <section className="toolbar" aria-label="控制栏">
        <div className="presetGroup" role="group" aria-label="翻译方向">
          {presets.map((preset) => (
            <button
              key={preset.label}
              className={
                sourceLanguage === preset.source && targetLanguage === preset.target
                  ? "preset active"
                  : "preset"
              }
              disabled={isRecording}
              onClick={() => applyPreset(preset.source, preset.target)}
            >
              {preset.label}
            </button>
          ))}
        </div>

        <label className="toggle">
          <input
            type="checkbox"
            checked={enableTts}
            onChange={(event) => setEnableTts(event.target.checked)}
          />
          <Volume2 size={17} aria-hidden="true" />
          TTS
        </label>

        <button
          className={isRecording ? "recordButton stop" : "recordButton"}
          onClick={() => {
            void (isRecording ? stop() : start()).catch((err: unknown) => {
              setError(err instanceof Error ? err.message : String(err));
              setStatus("出错");
            });
          }}
        >
          {isRecording ? <Square size={18} /> : <Mic size={18} />}
          {isRecording ? "停止" : "开始"}
        </button>
      </section>

      <section className="subtitleStage" aria-label="实时字幕">
        <div className="languageLine">
          {languageLabels[sourceLanguage]} → {languageLabels[targetLanguage]}
        </div>
        <div className="subtitle original">{transcript || "等待麦克风输入..."}</div>
        <div className="subtitle translated">{translation || finalTranslation || "译文会实时显示在这里"}</div>
      </section>

      <footer className="statusBar">
        <span>{status}</span>
        {error && <span className="errorText">{error}</span>}
      </footer>
    </main>
  );
}
