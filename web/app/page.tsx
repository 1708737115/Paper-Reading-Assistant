"use client";

import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertCircle,
  CheckCircle2,
  Download,
  FileText,
  KeyRound,
  Languages,
  Loader2,
  RefreshCw,
  UploadCloud
} from "lucide-react";
import { API_BASE, createJob, getJob, JobPublic, Provider, PROVIDERS } from "@/lib/api";

const completedStates = new Set(["completed", "failed"]);

function apiKeyStorageKey(provider: Provider) {
  return `paper-reader:${provider}:api-key`;
}

export default function Home() {
  const [provider, setProvider] = useState<Provider>("openai");
  const activeProvider = useMemo(() => PROVIDERS.find((item) => item.id === provider) ?? PROVIDERS[0], [provider]);
  const [model, setModel] = useState(activeProvider.defaultModel);
  const [apiKey, setApiKey] = useState("");
  const [rememberKey, setRememberKey] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [job, setJob] = useState<JobPublic | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    setModel(activeProvider.defaultModel);
    const savedKey = window.localStorage.getItem(apiKeyStorageKey(activeProvider.id)) ?? "";
    setApiKey(savedKey);
    setRememberKey(Boolean(savedKey));
  }, [activeProvider.defaultModel, activeProvider.id]);

  useEffect(() => {
    if (rememberKey && apiKey.trim()) {
      window.localStorage.setItem(apiKeyStorageKey(provider), apiKey.trim());
    }
  }, [apiKey, provider, rememberKey]);

  useEffect(() => {
    if (!job || completedStates.has(job.status)) {
      return;
    }

    const timer = window.setInterval(async () => {
      try {
        const fresh = await getJob(job.id);
        setJob(fresh);
      } catch (err) {
        setError(err instanceof Error ? err.message : "状态刷新失败");
      }
    }, 1500);

    return () => window.clearInterval(timer);
  }, [job]);

  const canSubmit = Boolean(file && apiKey.trim() && model.trim() && !submitting);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file) {
      setError("请选择 PDF 文件");
      return;
    }
    setSubmitting(true);
    setError(null);
    setJob(null);
    const trimmedApiKey = apiKey.trim();
    try {
      const created = await createJob({
        file,
        provider,
        model: model.trim(),
        apiKey: trimmedApiKey
      });
      if (rememberKey) {
        window.localStorage.setItem(apiKeyStorageKey(provider), trimmedApiKey);
      } else {
        window.localStorage.removeItem(apiKeyStorageKey(provider));
      }
      setJob(created);
      setApiKey(rememberKey ? trimmedApiKey : "");
    } catch (err) {
      setError(err instanceof Error ? err.message : "任务创建失败");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="app-shell">
      <section className="topbar">
        <div>
          <h1>双语文献阅读器</h1>
          <p>本地 OCR · 多模型翻译 · 对页导出</p>
        </div>
        <div className="service-pill">
          <span />
          127.0.0.1
        </div>
      </section>

      <section className="workspace">
        <form className="control-panel" onSubmit={handleSubmit}>
          <div className="panel-heading">
            <FileText size={18} />
            <span>文献</span>
          </div>

          <button
            className="upload-zone"
            type="button"
            onClick={() => fileInputRef.current?.click()}
            onDragOver={(event) => event.preventDefault()}
            onDrop={(event) => {
              event.preventDefault();
              const dropped = event.dataTransfer.files.item(0);
              if (dropped) {
                setFile(dropped);
              }
            }}
          >
            <UploadCloud size={24} />
            <span>{file ? file.name : "选择或拖入 PDF"}</span>
          </button>
          <input
            ref={fileInputRef}
            className="sr-only"
            type="file"
            accept="application/pdf,.pdf"
            onChange={(event) => setFile(event.target.files?.item(0) ?? null)}
          />

          <div className="field">
            <label>
              <Languages size={16} />
              供应商
            </label>
            <div className="segmented">
              {PROVIDERS.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  className={item.id === provider ? "active" : ""}
                  onClick={() => setProvider(item.id)}
                >
                  {item.label}
                </button>
              ))}
            </div>
          </div>

          <div className="field">
            <label htmlFor="model">模型</label>
            <input
              id="model"
              list="model-options"
              value={model}
              onChange={(event) => setModel(event.target.value)}
              spellCheck={false}
            />
            <datalist id="model-options">
              {activeProvider.models.map((item) => (
                <option value={item} key={item} />
              ))}
            </datalist>
          </div>

          <div className="field">
            <label htmlFor="apiKey">
              <KeyRound size={16} />
              API Key
            </label>
            <input
              id="apiKey"
              type="password"
              value={apiKey}
              placeholder={activeProvider.keyPlaceholder}
              autoComplete="off"
              onChange={(event) => setApiKey(event.target.value)}
            />
            <label className="checkbox-line">
              <input
                type="checkbox"
                checked={rememberKey}
                onChange={(event) => {
                  const checked = event.target.checked;
                  setRememberKey(checked);
                  if (!checked) {
                    window.localStorage.removeItem(apiKeyStorageKey(provider));
                  }
                }}
              />
              <span>保存 API Key 到本机浏览器</span>
            </label>
            <div className="field-note">{rememberKey ? "下次自动填入" : "仅本次任务使用"}</div>
          </div>

          <button className="primary-action" type="submit" disabled={!canSubmit}>
            {submitting ? <Loader2 className="spin" size={18} /> : <UploadCloud size={18} />}
            开始转换
          </button>

          {error ? (
            <div className="message error">
              <AlertCircle size={16} />
              <span>{error}</span>
            </div>
          ) : null}
        </form>

        <section className="result-panel">
          <div className="panel-heading">
            <RefreshCw size={18} />
            <span>任务</span>
          </div>
          {job ? <JobView job={job} /> : <EmptyState />}
        </section>
      </section>
    </main>
  );
}

function JobView({ job }: { job: JobPublic }) {
  const previewUrl = `${API_BASE}/jobs/${job.id}/preview`;
  const exportUrl = `${API_BASE}/jobs/${job.id}/export.pdf`;
  const failed = job.status === "failed";
  const completed = job.status === "completed";

  return (
    <div className="job-view">
      <div className="job-summary">
        <div>
          <div className="job-title">{job.filename}</div>
          <div className="job-meta">
            {job.provider} · {job.model} · {job.pages || "-"} 页
          </div>
        </div>
        <StatusBadge status={job.status} />
      </div>

      <div className="progress-track" aria-label="progress">
        <div style={{ width: `${job.progress}%` }} />
      </div>
      <div className="step-line">{job.current_step}</div>

      {failed && job.error ? (
        <div className="message error">
          <AlertCircle size={16} />
          <span>{job.error}</span>
        </div>
      ) : null}

      {completed ? (
        <>
          {job.warnings.length ? (
            <div className="warning-list">
              {job.warnings.slice(0, 5).map((item) => (
                <span key={item}>{item}</span>
              ))}
            </div>
          ) : null}
          <div className="actions-row">
            <a className="secondary-action" href={previewUrl} target="_blank" rel="noreferrer">
              打开预览
            </a>
            <a className="primary-action compact" href={exportUrl}>
              <Download size={18} />
              下载 PDF
            </a>
          </div>
          <iframe className="preview-frame" title="双语预览" src={previewUrl} />
        </>
      ) : null}
    </div>
  );
}

function EmptyState() {
  return (
    <div className="empty-state">
      <FileText size={26} />
      <span>等待任务</span>
    </div>
  );
}

function StatusBadge({ status }: { status: JobPublic["status"] }) {
  const label = {
    queued: "排队中",
    processing: "处理中",
    completed: "已完成",
    failed: "失败"
  }[status];
  const Icon = status === "completed" ? CheckCircle2 : status === "failed" ? AlertCircle : Loader2;
  return (
    <div className={`status-badge ${status}`}>
      <Icon className={status === "processing" || status === "queued" ? "spin" : ""} size={15} />
      {label}
    </div>
  );
}
