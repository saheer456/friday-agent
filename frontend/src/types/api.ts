export interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  streaming?: boolean;
}

export interface Phase {
  id: string;
  title: string;
  detail: string;
}

export interface SystemInfo {
  ui: {
    version: string;
  };
  voice: {
    stt_model: string;
    stt_device: string;
    stt_compute: string;
    tts_backend: string;
    tts_voice: string;
    vad_mode: number;
  };
  llm: {
    llm_provider: string;
    llm_model: string;
    llm_url_host: string;
  };
  readiness: {
    stt_ready: boolean;
    tts_ready: boolean;
    memory_ready: boolean;
  };
  history_turns: number;
}
