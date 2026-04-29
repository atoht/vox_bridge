import { ChevronDown, FileClock, Menu, Play, Square, Volume2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { buildWsUrl, requestTts } from "./api";
import { startPcmRecorder, type RecorderHandle } from "./audio";
import type { LanguageCode, ServerEvent, StreamConfig } from "./types";
import "./styles.css";

type TranslationEntry = {
  id: number;
  original: string;
  translated: string;
};

const languageLabels: Record<LanguageCode, string> = {
  zh: "简体中文",
  ja: "日本語",
  en: "English",
};

const languageFlags: Record<LanguageCode, string> = {
  zh: "🇨🇳",
  ja: "🇯🇵",
  en: "🇺🇸",
};

const presets: Array<{ label: string; source: LanguageCode; target: LanguageCode }> = [
  { label: "中 → 日", source: "zh", target: "ja" },
  { label: "日 → 中", source: "ja", target: "zh" },
  { label: "中 → 英", source: "zh", target: "en" },
  { label: "英 → 中", source: "en", target: "zh" },
  { label: "英 → 日", source: "en", target: "ja" },
  { label: "日 → 英", source: "ja", target: "en" },
];

function compactLanguageName(code: LanguageCode) {
  const label = languageLabels[code];
  return label.length > 5 ? `${label.slice(0, 5)}...` : label;
}

export default function App() {
  const [sourceLanguage, setSourceLanguage] = useState<LanguageCode>("zh");
  const [targetLanguage, setTargetLanguage] = useState<LanguageCode>("ja");
  const [enableTts, setEnableTts] = useState(false);
  const [status, setStatus] = useState("已停止");
  const [transcript, setTranscript] = useState("");
  const [translation, setTranslation] = useState("");
  const [finalTranslation, setFinalTranslation] = useState("");
  const [entries, setEntries] = useState<TranslationEntry[]>([]);
  const [error, setError] = useState("");
  const [isRecording, setIsRecording] = useState(false);

  const wsRef = useRef<WebSocket | null>(null);
  const recorderRef = useRef<RecorderHandle | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const transcriptRef = useRef("");
  const currentSourceTextRef = useRef("");
  const currentSegmentIdRef = useRef<number | null>(null);
  const entryIdRef = useRef(1);

  const directionValue = `${sourceLanguage}-${targetLanguage}`;
  const liveTranslatedText = translation || finalTranslation;
  const hasLiveCard = Boolean(transcript.trim() || liveTranslatedText.trim());

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

  function rememberFinalTranslation(
    translated: string,
    sourceText?: string,
    clearLive = true,
  ) {
    const original = sourceText || currentSourceTextRef.current || transcriptRef.current;
    if (!original.trim() || !translated.trim()) {
      return;
    }

    setEntries((prev) => [
      ...prev,
      {
        id: entryIdRef.current++,
        original,
        translated,
      },
    ]);
    if (clearLive) {
      currentSourceTextRef.current = "";
      currentSegmentIdRef.current = null;
      transcriptRef.current = "";
      setTranscript("");
      setTranslation("");
      setFinalTranslation("");
    }
  }

  function handleServerEvent(event: ServerEvent) {
    if (event.type === "ready") {
      setStatus("正在实时翻译");
    } else if (event.type === "speech.started") {
      setStatus("正在聆听");
    } else if (event.type === "speech.stopped") {
      setStatus("正在生成译文");
    } else if (event.type === "transcript.delta" || event.type === "transcript.done") {
      if (event.segment_id !== undefined && event.segment_id !== currentSegmentIdRef.current) {
        currentSegmentIdRef.current = event.segment_id;
        currentSourceTextRef.current = event.text;
        setTranslation("");
        setFinalTranslation("");
      }
      transcriptRef.current = event.text;
      setTranscript(event.text);
    } else if (event.type === "translation.reset") {
      if (event.segment_id !== undefined && event.segment_id !== currentSegmentIdRef.current) {
        currentSegmentIdRef.current = event.segment_id;
        setTranslation("");
        setFinalTranslation("");
      }
      currentSourceTextRef.current = event.text;
    } else if (event.type === "translation.delta") {
      if (event.segment_id !== undefined && event.segment_id !== currentSegmentIdRef.current) {
        return;
      }
      setTranslation(event.text);
    } else if (event.type === "translation.done") {
      if (!event.text.trim()) {
        return;
      }
      if (event.is_final) {
        const isCurrentSegment =
          event.segment_id === undefined || event.segment_id === currentSegmentIdRef.current;
        rememberFinalTranslation(event.text, event.source_text, isCurrentSegment);
        if (enableTts) {
          void playTts(event.text).catch((err: unknown) => {
            setError(err instanceof Error ? err.message : String(err));
          });
        }
      } else if (
        event.segment_id === undefined ||
        event.segment_id === currentSegmentIdRef.current
      ) {
        setTranslation(event.text);
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
    setEntries([]);
    transcriptRef.current = "";
    currentSourceTextRef.current = "";
    currentSegmentIdRef.current = null;
    setStatus("正在连接");

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

  function applyDirection(value: string) {
    const [source, target] = value.split("-") as [LanguageCode, LanguageCode];
    setSourceLanguage(source);
    setTargetLanguage(target);
  }

  return (
    <main className="appShell">
      <header className="topBar" aria-label="语言控制栏">
        <button className="iconButton" type="button" aria-label="菜单">
          <Menu size={25} />
        </button>

        <div className="languageSelector">
          <span>{languageFlags[sourceLanguage]}</span>
          <span>{compactLanguageName(sourceLanguage)}</span>
          <ChevronDown size={16} />
        </div>

        <div className="swapBadge" aria-hidden="true">
          ⇆
        </div>

        <label className="directionSelectLabel">
          <span className="languageSelector target">
            <span>{languageFlags[targetLanguage]}</span>
            <span>{compactLanguageName(targetLanguage)}</span>
            <ChevronDown size={16} />
          </span>
          <select
            aria-label="翻译方向"
            value={directionValue}
            disabled={isRecording}
            onChange={(event) => applyDirection(event.target.value)}
          >
            {presets.map((preset) => (
              <option key={preset.label} value={`${preset.source}-${preset.target}`}>
                {preset.label}
              </option>
            ))}
          </select>
        </label>

        <button className="iconButton" type="button" aria-label="历史">
          <FileClock size={25} />
        </button>
      </header>

      <section className="promptBanner" aria-label="开始提示">
        <p>👇 下のボタンをクリックしてください</p>
        <p>▶️ 話し始めると、Vox Bridge が自動的に言語を認識して翻訳します</p>
        <Volume2 size={24} className="bannerIcon" />
      </section>

      <section className="transcriptList" aria-label="实时翻译内容">
        {entries.map((entry) => (
          <article className="translationCard" key={entry.id}>
            <p className="originalText">{entry.original}</p>
            <div className="translatedRow">
              <p className="translatedText">{entry.translated}</p>
              <button
                className="soundButton"
                type="button"
                aria-label="播放译文"
                onClick={() => {
                  void playTts(entry.translated).catch((err: unknown) => {
                    setError(err instanceof Error ? err.message : String(err));
                  });
                }}
              >
                <Volume2 size={22} />
              </button>
            </div>
          </article>
        ))}

        {hasLiveCard && (
          <article className="translationCard liveCard">
            <p className="originalText">{transcript || "正在识别..."}</p>
            <div className="translatedRow">
              <p className="translatedText">{liveTranslatedText || "正在翻译..."}</p>
              <Volume2 size={22} className="inlineSound" />
            </div>
          </article>
        )}

        {!entries.length && !hasLiveCard && (
          <article className="emptyCard">
            <p>点击下方按钮开始实时翻译</p>
            <p>{languageFlags[sourceLanguage]} {languageLabels[sourceLanguage]} → {languageFlags[targetLanguage]} {languageLabels[targetLanguage]}</p>
          </article>
        )}
      </section>

      <footer className="bottomDock">
        <div className="dockLine" />
        <button
          className={isRecording ? "primaryControl recording" : "primaryControl"}
          type="button"
          aria-label={isRecording ? "停止" : "开始"}
          onClick={() => {
            void (isRecording ? stop() : start()).catch((err: unknown) => {
              setError(err instanceof Error ? err.message : String(err));
              setStatus("出错");
            });
          }}
        >
          {isRecording ? <Square size={28} /> : <Play size={34} />}
        </button>
        <label className="ttsSwitch">
          <input
            type="checkbox"
            checked={enableTts}
            onChange={(event) => setEnableTts(event.target.checked)}
          />
          <Volume2 size={18} />
          TTS
        </label>
        <div className="statusText">
          <span>{status}</span>
          {error && <span className="errorText">{error}</span>}
        </div>
      </footer>
    </main>
  );
}
