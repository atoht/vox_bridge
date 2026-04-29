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
  | { type: "transcript.delta"; delta: string; text: string; segment_id?: number }
  | { type: "transcript.done"; text: string; segment_id?: number }
  | { type: "translation.reset"; text: string; is_final: boolean; segment_id?: number }
  | {
      type: "translation.delta";
      delta: string;
      text: string;
      is_final: boolean;
      segment_id?: number;
    }
  | {
      type: "translation.done";
      text: string;
      is_final: boolean;
      segment_id?: number;
      source_text?: string;
    }
  | { type: "translation.last"; text: string }
  | { type: "warning"; message: string }
  | { type: "error"; message: string };
