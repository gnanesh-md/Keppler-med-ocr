// Thin fetch wrapper for the Keppler FastAPI backend.
// In dev, Vite proxies /api -> http://localhost:8000 (see vite.config.ts),
// so the default base of "/api/v1" works without any CORS setup.
const API_BASE = (import.meta as any).env?.VITE_API_BASE_URL || "/api/v1";

const TOKEN_KEY = "keppler_token";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string | null) {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = { ...((options.headers as Record<string, string>) || {}) };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  if (options.body && !(options.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
  }
  
  // Always include localtunnel bypass header for tunneling environments
  headers["Bypass-Tunnel-Reminder"] = "true";

  const res = await fetch(`${API_BASE}${path}`, { ...options, headers });

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = await res.json();
      detail = data.detail ? String(data.detail) : JSON.stringify(data);
    } catch {
      /* response wasn't JSON */
    }
    throw new ApiError(res.status, detail);
  }

  const contentType = res.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    return (await res.json()) as T;
  }
  return (await res.text()) as unknown as T;
}

const get = <T>(path: string) => request<T>(path, { method: "GET" });
const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", body: body !== undefined ? JSON.stringify(body) : undefined });
const postForm = <T>(path: string, form: FormData) => request<T>(path, { method: "POST", body: form });

async function downloadBlob(path: string, filename: string) {
  const token = getToken();
  const res = await fetch(`${API_BASE}${path}`, {
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      "Bypass-Tunnel-Reminder": "true",
    },
  });
  if (!res.ok) throw new ApiError(res.status, "Export failed");
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

// ─── Auth ──────────────────────────────────────────────────────────────────

export interface AuthUser {
  user_id: number;
  username: string;
}

export const authApi = {
  login: (username: string, password: string) =>
    post<{ access_token: string; token_type: string; user_id: number; username: string }>("/auth/login", {
      username,
      password,
    }),
  register: (username: string, password: string) =>
    post<{ message: string }>("/auth/register", { username, password }),
  me: () => get<AuthUser>("/auth/me"),
};

// ─── OCR ───────────────────────────────────────────────────────────────────

export interface OCREntity {
  "Original Text"?: string;
  "Predicted Code"?: string;
  "Predicted Name"?: string;
  Type?: string;
  Confidence?: string;
  page?: number;
  bbox?: number[];
}

export interface JobStatus {
  job_id: string;
  status: "PENDING" | "PROCESSING" | "COMPLETED" | "FAILED";
  progress: number;
  error_message: string | null;
}

export interface OCRJobResult {
  filename: string;
  combined_markdown: string;
  pages: { label: string; text: string }[];
  entities: OCREntity[];
  confidence_score: number;
  extraction_time: number | null;
}

export const ocrApi = {
  blueprints: () => get<{ blueprints: string[] }>("/ocr/blueprints"),
  upload: (file: File, clientBlueprint: string) => {
    const form = new FormData();
    form.append("file", file);
    form.append("client_blueprint", clientBlueprint);
    return postForm<{ document_hash: string; job_id: string; message: string }>("/ocr/upload", form);
  },
  jobStatus: (jobId: string) => get<JobStatus>(`/ocr/job/${jobId}`),
  result: (jobId: string) => get<OCRJobResult>(`/ocr/job/${jobId}/result`),
  downloadExport: (jobId: string, format: "md" | "json" | "pdf" | "docx" | "xlsx", filename: string) =>
    downloadBlob(`/ocr/job/${jobId}/export?format=${format}`, filename),
  getOriginalFileUrl: async (jobId: string) => {
    const token = getToken();
    const res = await fetch(`${API_BASE}/ocr/job/${jobId}/original`, {
      headers: {
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        "Bypass-Tunnel-Reminder": "true",
      },
    });
    if (!res.ok) throw new ApiError(res.status, "Failed to load original image");
    const blob = await res.blob();
    return URL.createObjectURL(blob);
  },
};

// ─── PDF Summarizer ─────────────────────────────────────────────────────────

export interface SummarizerJobResult {
  filename: string;
  summary_md: string;
  page_texts: Record<string, string>;
  patient_meta: { name?: string; ip_no?: string; doctor?: string; nurse?: string };
}

export const summarizerApi = {
  upload: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return postForm<{ document_hash: string; job_id: string; message: string }>("/summarizer/upload", form);
  },
  jobStatus: (jobId: string) => get<JobStatus>(`/summarizer/job/${jobId}`),
  result: (jobId: string) => get<SummarizerJobResult>(`/summarizer/job/${jobId}/result`),
  downloadExport: (jobId: string, format: "md" | "pdf" | "docx", filename: string) =>
    downloadBlob(`/summarizer/job/${jobId}/export?format=${format}`, filename),
};

// ─── Document Vault ─────────────────────────────────────────────────────────

export interface VaultDoc {
  id: number;
  filename: string;
  doc_category: string | null;
  confidence_score: number | null;
  extraction_date: string | null;
}

export const vaultApi = {
  list: () => get<VaultDoc[]>("/vault"),
  get: (docId: number) => get<{ id: number; markdown: string }>(`/vault/${docId}`),
};

// ─── AI Assistant (RAG chat) ────────────────────────────────────────────────

export interface Citation {
  doc_id: number;
  filename: string;
  page_label: string;
  snippet: string;
}

export interface ChatMessage {
  role: string;
  content: string;
  citations?: Citation[];
}

export const assistantApi = {
  chat: (message: string, sessionId: string, targetLanguage = "English") =>
    post<{ role: string; content: string; citations: Citation[] }>("/assistant/chat", {
      message,
      session_id: sessionId,
      target_language: targetLanguage,
    }),
  history: (sessionId: string) => get<ChatMessage[]>(`/assistant/history?session_id=${encodeURIComponent(sessionId)}`),
  ingestText: (documents: string[]) => post<{ message: string }>("/assistant/ingest/text", { documents }),
  ingestVaultDocs: (docIds: number[]) => post<{ message: string }>("/assistant/ingest/vault", { doc_ids: docIds }),

  // Streaming variant: POST + auth header, so EventSource (GET-only, no custom
  // headers) doesn't work here — consume the SSE body via fetch + ReadableStream
  // instead. Calls onCitations once, onToken per chunk, onDone at the end.
  chatStream: async (
    message: string,
    sessionId: string,
    handlers: { onCitations?: (c: Citation[]) => void; onToken?: (text: string) => void; onDone?: () => void; onError?: (msg: string) => void },
    targetLanguage = "English"
  ) => {
    const token = getToken();
    const res = await fetch(`${API_BASE}/assistant/chat/stream`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        "Bypass-Tunnel-Reminder": "true",
      },
      body: JSON.stringify({ message, session_id: sessionId, target_language: targetLanguage }),
    });
    if (!res.ok || !res.body) {
      throw new ApiError(res.status, res.statusText || "Streaming request failed");
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      const lines = buffer.split("\n\n");
      buffer = lines.pop() ?? "";
      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        const event = JSON.parse(line.slice(6));
        if (event.type === "citations") handlers.onCitations?.(event.citations);
        else if (event.type === "token") handlers.onToken?.(event.text);
        else if (event.type === "error") handlers.onError?.(event.message);
        else if (event.type === "done") handlers.onDone?.();
      }
    }
  },
};

// ─── Dashboard ──────────────────────────────────────────────────────────────

export interface ActiveJob {
  job_id: string;
  job_type: string;
  status: string;
  progress: number;
  filename: string | null;
}

export interface DashboardSummary {
  vault_document_count: number;
  active_jobs: ActiveJob[];
  recent_documents: VaultDoc[];
}

export const dashboardApi = {
  summary: () => get<DashboardSummary>("/dashboard/summary"),
};
