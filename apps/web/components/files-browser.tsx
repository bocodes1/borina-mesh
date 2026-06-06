"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import ReactMarkdown from "react-markdown";
import { FileText, FileType, Image as ImageIcon, Download, Search, X, ExternalLink, Send } from "lucide-react";
import { api, type FilesResponse, type FileItem } from "@/lib/api";
import { SectionHeader } from "@/components/ui/section-header";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { SkeletonCard } from "@/components/ui/loading-skeleton";

const IMG = ["png", "jpg", "jpeg", "gif", "webp", "svg"];
function fmtSize(n: number) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}
function fileIcon(t: string) {
  if (t === "pdf") return <FileType className="h-4 w-4 text-negative" />;
  if (IMG.includes(t)) return <ImageIcon className="h-4 w-4 text-brand-2" />;
  return <FileText className="h-4 w-4 text-brand" />;
}
function srcLabel(s: string) {
  return s === "schedule_daily" ? "daily brief" : s === "uploaded" ? "uploaded" : s;
}

export function FilesBrowser() {
  const [q, setQ] = useState("");
  const [source, setSource] = useState("all");
  const [type, setType] = useState("all");
  const [data, setData] = useState<FilesResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<FileItem | null>(null);

  const load = useCallback(
    () => api.listFiles({ source, type, q }).then((d) => { setData(d); setError(null); }).catch((e) => setError(e.message)),
    [source, type, q],
  );
  useEffect(() => {
    load();
    const id = setInterval(load, 8000); // new outputs animate in as tasks produce them
    return () => clearInterval(id);
  }, [load]);

  const groups = useMemo(() => {
    const g: Record<string, FileItem[]> = {};
    for (const f of data?.files ?? []) (g[f.source] ||= []).push(f);
    return Object.entries(g);
  }, [data]);

  return (
    <div>
      <SectionHeader
        title="Files"
        description={data ? `${data.count} files` : "loading…"}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative">
              <Search className="absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
              <input
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="search files…"
                aria-label="search files"
                className="w-40 rounded border border-border bg-surface py-1 pl-7 pr-2 font-mono text-xs outline-none focus:border-brand"
              />
            </div>
            <select value={source} onChange={(e) => setSource(e.target.value)} aria-label="filter source" className="rounded border border-border bg-surface px-2 py-1 font-mono text-xs">
              <option value="all">all sources</option>
              {(data?.sources ?? []).map((s) => <option key={s} value={s}>{srcLabel(s)}</option>)}
            </select>
            <select value={type} onChange={(e) => setType(e.target.value)} aria-label="filter type" className="rounded border border-border bg-surface px-2 py-1 font-mono text-xs">
              <option value="all">all types</option>
              {(data?.types ?? []).map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>
        }
      />

      {error ? (
        <ErrorState message={error} onRetry={load} />
      ) : data === null ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">{Array.from({ length: 6 }).map((_, i) => <SkeletonCard key={i} />)}</div>
      ) : data.files.length === 0 ? (
        <EmptyState title="No files" description="Task outputs and uploads land here." icon={<FileText />} />
      ) : (
        <div className="space-y-6">
          {groups.map(([src, files]) => (
            <section key={src}>
              <h3 className="mb-2 font-mono text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
                <span className="text-brand">/</span> {srcLabel(src)} <span className="text-muted-foreground/50">({files.length})</span>
              </h3>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                <AnimatePresence initial={false}>
                  {files.map((f) => (
                    <motion.button
                      key={f.path}
                      layout
                      initial={{ opacity: 0, scale: 0.97 }}
                      animate={{ opacity: 1, scale: 1 }}
                      exit={{ opacity: 0 }}
                      onClick={() => setPreview(f)}
                      className="surface-card flex flex-col gap-2 rounded-lg p-3 text-left hover:border-brand/30"
                    >
                      <div className="flex items-start gap-2">
                        {fileIcon(f.type)}
                        <span className="min-w-0 flex-1 truncate font-mono text-xs text-foreground/90">{f.name}</span>
                        <a href={`/api/artifacts/${f.path}`} download onClick={(e) => e.stopPropagation()} aria-label={`download ${f.name}`} className="shrink-0 text-muted-foreground hover:text-brand">
                          <Download className="h-4 w-4" />
                        </a>
                      </div>
                      {f.source === "telegram" && f.prompt ? (
                        <span className="flex items-center gap-1 truncate font-mono text-[10px] text-brand-2"><Send className="h-3 w-3" />“{f.prompt}”</span>
                      ) : null}
                      <div className="mt-auto flex items-center justify-between font-mono text-[10px] text-muted-foreground/60">
                        <span className="tabular-nums">{f.date}</span>
                        <span className="tabular-nums">{fmtSize(f.size_bytes)} · {f.type}</span>
                      </div>
                    </motion.button>
                  ))}
                </AnimatePresence>
              </div>
            </section>
          ))}
        </div>
      )}

      {preview ? <PreviewPanel file={preview} onClose={() => setPreview(null)} /> : null}
    </div>
  );
}

function PreviewPanel({ file, onClose }: { file: FileItem; onClose: () => void }) {
  const [text, setText] = useState<string | null>(null);
  const url = `/api/artifacts/${file.path}`;
  const isImg = IMG.includes(file.type);
  const isPdf = file.type === "pdf";
  const isText = !isImg && !isPdf;

  useEffect(() => {
    if (!isText) return;
    fetch(url).then((r) => r.text()).then(setText).catch(() => setText("(could not load preview)"));
  }, [url, isText]);

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/50" onClick={onClose} role="presentation">
      <motion.div
        initial={{ x: 40, opacity: 0 }}
        animate={{ x: 0, opacity: 1 }}
        onClick={(e) => e.stopPropagation()}
        className="flex h-full w-full max-w-2xl flex-col border-l border-foreground/10 bg-surface"
        role="dialog"
        aria-label={`preview ${file.name}`}
      >
        <div className="flex items-center justify-between border-b border-foreground/8 px-4 py-3">
          <span className="flex items-center gap-2 truncate font-mono text-sm font-semibold">{fileIcon(file.type)} {file.name}</span>
          <div className="flex items-center gap-3">
            {file.job_id ? <a href={`/jobs`} className="flex items-center gap-1 font-mono text-xs text-brand"><ExternalLink className="h-3 w-3" />job #{file.job_id}</a> : null}
            <a href={url} download className="text-muted-foreground hover:text-brand"><Download className="h-4 w-4" /></a>
            <button onClick={onClose} aria-label="close" className="text-muted-foreground hover:text-foreground"><X className="h-4 w-4" /></button>
          </div>
        </div>
        <div className="flex-1 overflow-auto p-4">
          {isPdf ? (
            <iframe title={file.name} src={url} className="h-full min-h-[70vh] w-full rounded border border-foreground/8 bg-white" />
          ) : isImg ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={url} alt={file.name} className="mx-auto max-h-full rounded border border-foreground/8" />
          ) : text === null ? (
            <p className="font-mono text-xs text-muted-foreground">loading…</p>
          ) : file.type === "md" ? (
            <div className="prose prose-invert prose-sm max-w-none">
              <ReactMarkdown>{text}</ReactMarkdown>
            </div>
          ) : (
            <pre className="whitespace-pre-wrap rounded border border-foreground/8 bg-surface-2 p-3 font-mono text-xs">{text}</pre>
          )}
        </div>
      </motion.div>
    </div>
  );
}
