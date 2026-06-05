"use client";

import { useEffect, useState } from "react";
import { Download, Loader2 } from "lucide-react";
import { useParams } from "next/navigation";
import { API_BASE, getJob, JobPublic } from "@/lib/api";

export default function JobPage() {
  const params = useParams<{ id: string }>();
  const [job, setJob] = useState<JobPublic | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const fresh = await getJob(params.id);
        if (active) {
          setJob(fresh);
        }
      } catch (err) {
        if (active) {
          setError(err instanceof Error ? err.message : "任务读取失败");
        }
      }
    }
    load();
    const timer = window.setInterval(load, 1500);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [params.id]);

  if (error) {
    return <main className="center-page">{error}</main>;
  }

  if (!job || job.status !== "completed") {
    return (
      <main className="center-page">
        <Loader2 className="spin" size={20} />
        {job?.current_step ?? "读取任务"}
      </main>
    );
  }

  return (
    <main className="job-page">
      <div className="job-page-toolbar">
        <span>{job.filename}</span>
        <a className="primary-action compact" href={`${API_BASE}/jobs/${job.id}/export.pdf`}>
          <Download size={18} />
          下载 PDF
        </a>
      </div>
      <iframe className="full-preview" title="双语预览" src={`${API_BASE}/jobs/${job.id}/preview`} />
    </main>
  );
}
