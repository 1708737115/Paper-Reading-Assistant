export type Provider = "openai" | "deepseek";

export type JobStatus = "queued" | "processing" | "completed" | "failed";

export type JobPublic = {
  id: string;
  filename: string;
  provider: Provider;
  model: string;
  status: JobStatus;
  progress: number;
  current_step: string;
  pages: number;
  created_at: string;
  updated_at: string;
  error?: string | null;
  warnings: string[];
};

export type ProviderOption = {
  id: Provider;
  label: string;
  defaultModel: string;
  models: string[];
  keyPlaceholder: string;
};

export const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

export const PROVIDERS: ProviderOption[] = [
  {
    id: "openai",
    label: "OpenAI",
    defaultModel: "gpt-5.5",
    models: ["gpt-5.5", "gpt-5.4", "gpt-5.4-mini"],
    keyPlaceholder: "sk-..."
  },
  {
    id: "deepseek",
    label: "DeepSeek",
    defaultModel: "deepseek-v4-pro",
    models: ["deepseek-v4-pro", "deepseek-v4-flash"],
    keyPlaceholder: "sk-..."
  }
];

export async function createJob(input: {
  file: File;
  provider: Provider;
  model: string;
  apiKey: string;
}): Promise<JobPublic> {
  const form = new FormData();
  form.append("file", input.file);
  form.append("provider", input.provider);
  form.append("model", input.model);
  form.append("apiKey", input.apiKey);

  const response = await fetch(`${API_BASE}/jobs`, {
    method: "POST",
    body: form
  });
  return parseResponse<JobPublic>(response);
}

export async function getJob(jobId: string): Promise<JobPublic> {
  const response = await fetch(`${API_BASE}/jobs/${jobId}`, { cache: "no-store" });
  return parseResponse<JobPublic>(response);
}

async function parseResponse<T>(response: Response): Promise<T> {
  const contentType = response.headers.get("content-type") ?? "";
  const payload = contentType.includes("application/json")
    ? await response.json()
    : { detail: await response.text() };

  if (!response.ok) {
    const detail = typeof payload.detail === "string" ? payload.detail : JSON.stringify(payload.detail ?? payload);
    throw new Error(detail);
  }

  return payload as T;
}
