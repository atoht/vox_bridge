export type LanguageCode = "zh" | "ja" | "en";

export type StreamConfig = {
  source_language: LanguageCode;
  target_language: LanguageCode;
  enable_tts: boolean;
};

export type ServerEvent =
  | { type: "ready" }
  | { type: "speech.started" }
  | { type: "speech.stopped" }
  | { type: "transcript.delta"; delta: string; text: string }
  | { type: "transcript.done"; text: string }
  | { type: "translation.reset"; text: string; is_final: boolean }
  | { type: "translation.delta"; delta: string; text: string; is_final: boolean }
  | { type: "translation.done"; text: string; is_final: boolean }
  | { type: "translation.last"; text: string }
  | { type: "warning"; message: string }
  | { type: "error"; message: string };
