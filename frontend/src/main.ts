/**
 * House Document Search - Frontend
 *
 * Single-page Vue app for uploading house documents (PDFs, DOCX, etc.)
 * and searching or asking AI questions about their contents.
 */

import { createApp, h, reactive, computed } from "vue";

// -- Types --

type SearchResult = {
  document_id: string;
  chunk_id: string;
  title: string;
  snippet: string;
  score: number;
  source_type: string;
  document_type: string;
};

type Citation = {
  document_id: string;
  chunk_id: string;
  title: string;
  snippet: string;
};

type DocInfo = {
  document_id: string;
  title: string;
  document_type: string;
  category: string;
  status: string;
};

// -- API base URL detection --
// Adjusts automatically depending on how you access the app:
//   https://app.localhost  -> https://api.localhost
//   http://localhost:5173  -> http://localhost:8000

const apiBase = location.hostname === "app.localhost"
  ? `${location.protocol}//api.localhost`
  : location.hostname === "localhost" && location.port === "5173"
    ? "http://localhost:8000"
    : `${location.protocol}//${location.hostname}:8000`;

// -- Reactive state --

const state = reactive({
  // Upload
  uploadFiles: [] as File[],
  uploadLoading: false,
  uploadStatus: "",
  uploadLog: [] as Array<{
    file: string;
    status: "uploading" | "done" | "error";
    detail: string;
    log?: string[];
  }>,

  // Search / Ask / Settings mode
  query: "",
  mode: "search" as "search" | "ask" | "create" | "health" | "settings",
  searchLoading: false,
  searchError: "",
  searchTime: null as number | null,
  results: [] as SearchResult[],
  answer: "",
  citations: [] as Citation[],

  // Document list
  documents: [] as DocInfo[],

  // Settings
  healthChecks: null as any,
  healthErrors: [] as string[],
  healthLoading: false,
  healthOpen: true,
  configOpen: false,
  config: {} as Record<string, string>,
  configEdits: {} as Record<string, string>,
  qaModels: [] as Array<{ id: string; label: string }>,
  visionModels: [] as Array<{ id: string; label: string }>,
  modelWarnings: [] as string[],
  usageOpen: false,
  usageData: null as any,
  pricingRegion: "",
  pricingUrl: "",

  // Create/Generate
  generatePrompt: "",
  generateFormat: "md" as string,
  generateLoading: false,
  generateResult: "" as string,
  generateError: "",
  generateSelectedDocs: [] as string[],
  generateFileB64: "" as string,
  generateFilename: "" as string,
  generateDone: false,
  generateDownloading: false,
  generateHistory: [] as Array<{ prompt: string; markdown: string; timestamp: string }>,
  detectedFormat: "" as string,
  detectedReason: "" as string,
  detectedAccepted: null as boolean | null,
  detectingFormat: false,

  // K8s Health
  k8sHealth: null as any,
  k8sLoading: false,
});

const hasResults = computed(() => state.results.length > 0 || state.answer);

// -- API calls --

async function loadDocuments() {
  try {
    state.documents = await (await fetch(`${apiBase}/documents`)).json();
  } catch {
    // Backend might not be running yet
  }
}

async function upload() {
  if (state.uploadFiles.length === 0) {
    state.uploadStatus = "Choose files or a folder first";
    return;
  }

  // Filter to supported types
  const supported = [".pdf", ".docx", ".doc", ".txt", ".md", ".jpg", ".jpeg", ".png", ".tiff", ".tif"];
  const files = state.uploadFiles.filter(f =>
    supported.some(ext => f.name.toLowerCase().endsWith(ext))
  );
  if (files.length === 0) {
    state.uploadStatus = "No supported files found (PDF, DOCX, DOC, TXT, MD, JPG, PNG, TIFF)";
    return;
  }

  state.uploadLoading = true;
  state.uploadStatus = "";
  state.uploadLog = [];

  const body = new FormData();
  for (const file of files) body.append("files", file);

  try {
    const res = await fetch(`${apiBase}/ingest/upload-stream`, { method: "POST", body });
    if (!res.ok) {
      state.uploadStatus = `Upload failed: ${await res.text()}`;
      state.uploadLoading = false;
      return;
    }

    const reader = res.body!.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      // Parse SSE lines
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";
      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        const msg = JSON.parse(line.slice(6));

        if (msg.type === "progress") {
          state.uploadLog.push({ file: msg.file, status: "uploading", detail: `${msg.current}/${msg.total} Extracting text...` });
        } else if (msg.type === "done") {
          // Update the last log entry for this file
          const idx = state.uploadLog.findLastIndex((l: any) => l.file === msg.file);
          if (idx >= 0) {
            state.uploadLog[idx] = { file: msg.file, status: "done", detail: `${msg.category} / ${msg.document_type}`, log: msg.log || [] };
          }
        } else if (msg.type === "error") {
          const idx = state.uploadLog.findLastIndex((l: any) => l.file === msg.file);
          if (idx >= 0) {
            state.uploadLog[idx] = { file: msg.file, status: "error", detail: msg.error };
          }
        } else if (msg.type === "complete") {
          state.uploadStatus = `Done: ${msg.uploaded} indexed, ${msg.errors} failed out of ${msg.total}`;
        }
      }
    }

    // Reset
    state.uploadFiles = [];
    const inputs = document.querySelectorAll('input[type="file"]') as NodeListOf<HTMLInputElement>;
    inputs.forEach(el => el.value = "");
    await loadDocuments();
  } catch (e: any) {
    state.uploadStatus = `Upload error: ${e.message || "Could not reach server"}`;
  } finally {
    state.uploadLoading = false;
  }
}

async function loadHealthCheck() {
  state.healthLoading = true;
  try {
    const resp = await fetch(`${apiBase}/admin/health-check`);
    const data = await resp.json();
    state.healthChecks = data.checks;
    state.healthErrors = data.errors || [];
  } catch (e: any) {
    state.healthErrors = [`Could not reach API: ${e.message}`];
  } finally {
    state.healthLoading = false;
  }
}

let _detectTimer: any = null;

function onPromptInput(val: string) {
  state.generatePrompt = val;
  state.detectedAccepted = null;
  // Debounce: detect format 800ms after user stops typing
  clearTimeout(_detectTimer);
  if (val.trim().length > 10) {
    _detectTimer = setTimeout(detectFormat, 800);
  }
}

async function detectFormat() {
  if (!state.generatePrompt.trim()) return;
  state.detectingFormat = true;
  try {
    const resp = await fetch(`${apiBase}/generate/detect-format`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt: state.generatePrompt }),
    });
    if (resp.ok) {
      const data = await resp.json();
      state.detectedFormat = data.format;
      state.detectedReason = data.reason;
      state.detectedAccepted = true;
      state.generateFormat = data.format;
    }
  } catch { /* ignore */ }
  finally { state.detectingFormat = false; }
}

async function generateDoc() {
  if (!state.generatePrompt.trim()) return;
  state.generateLoading = true;
  state.generateError = "";
  state.generateResult = "";
  state.generateDone = false;
  try {
    // Always generate as markdown first (cheapest, Bedrock call)
    const resp = await fetch(`${apiBase}/generate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        prompt: state.generatePrompt,
        format: state.generateFormat,
        document_ids: state.generateSelectedDocs.length > 0 ? state.generateSelectedDocs : undefined,
      }),
    });
    if (!resp.ok) {
      const err = await resp.json();
      state.generateError = err.detail || "Generation failed";
      return;
    }
    const data = await resp.json();
    state.generateResult = data.markdown;
    state.generateDone = true;
    // Save to history
    state.generateHistory.unshift({
      prompt: state.generatePrompt,
      markdown: data.markdown,
      format: state.generateFormat,
      timestamp: new Date().toLocaleTimeString(),
    });
    if (state.generateHistory.length > 10) state.generateHistory.pop();
  } catch (e: any) {
    state.generateError = e.message || "Could not reach server";
  } finally {
    state.generateLoading = false;
  }
}

async function downloadGenerated(markdown?: string) {
  const content = markdown || state.generateResult;
  if (!content) return;
  const fmt = state.generateFormat;

  if (fmt === "md") {
    const blob = new Blob([content], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = "generated.md"; a.click();
    URL.revokeObjectURL(url);
    return;
  }

  // Call backend to convert markdown to the selected format
  state.generateDownloading = true;
  try {
    const resp = await fetch(`${apiBase}/generate/convert`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ markdown: content, format: fmt }),
    });
    if (!resp.ok) {
      state.generateError = "Conversion failed";
      return;
    }
    const data = await resp.json();
    const byteChars = atob(data.file_b64);
    const byteArray = new Uint8Array(byteChars.length);
    for (let i = 0; i < byteChars.length; i++) byteArray[i] = byteChars.charCodeAt(i);
    const blob = new Blob([byteArray]);
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = data.filename; a.click();
    URL.revokeObjectURL(url);
  } catch (e: any) {
    state.generateError = e.message || "Download failed";
  } finally {
    state.generateDownloading = false;
  }
}

async function loadUsage() {
  try {
    const resp = await fetch(`${apiBase}/admin/usage`);
    state.usageData = await resp.json();
  } catch { /* ignore */ }
}

async function loadK8sHealth() {
  state.k8sLoading = true;
  try {
    const resp = await fetch(`${apiBase}/admin/k8s-health`);
    state.k8sHealth = await resp.json();
  } catch { /* ignore */ }
  state.k8sLoading = false;
}

function checkModelWarnings() {
  const warnings: string[] = [];
  if (!state.config.BEDROCK_MODEL_ID) {
    warnings.push("No Ask AI model selected. Go to Settings to pick one.");
  }
  if (!state.config.BEDROCK_VISION_MODEL_ID) {
    warnings.push("No Vision OCR model selected. Scanned PDFs won't be readable.");
  }
  state.modelWarnings = warnings;
}

async function loadConfig() {
  try {
    const [configResp, modelsResp] = await Promise.all([
      fetch(`${apiBase}/admin/config`),
      fetch(`${apiBase}/admin/models`),
    ]);
    state.config = await configResp.json();
    state.configEdits = { ...state.config };
    const models = await modelsResp.json();
    state.qaModels = models.qa || [];
    state.visionModels = models.vision || [];
    checkModelWarnings();
  } catch {
    /* ignore */
  }
}

async function saveConfig() {
  const resp = await fetch(`${apiBase}/admin/config`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(state.configEdits),
  });
  if (resp.ok) {
    await loadConfig();
    await loadHealthCheck();
    checkModelWarnings();
  }
}

async function viewDoc(id: string) {
  const key = `view_${id}`;
  if ((state as any)[key]) {
    (state as any)[key] = null;  // toggle off
    return;
  }
  try {
    const resp = await fetch(`${apiBase}/documents/${id}/chunks`);
    const data = await resp.json();
    const fullText = data.chunks.map((c: any) => c.content).join("\n\n");
    (state as any)[key] = fullText || "(no text extracted)";
  } catch {
    (state as any)[key] = "(failed to load)";
  }
}

async function deleteDoc(id: string) {
  await fetch(`${apiBase}/documents/${id}`, { method: "DELETE" });
  await loadDocuments();
}

async function deleteAll() {
  if (!confirm(`Delete all ${state.documents.length} documents? This cannot be undone.`)) return;
  await fetch(`${apiBase}/documents`, { method: "DELETE" });
  await loadDocuments();
}

async function submit() {
  if (!state.query.trim()) return;

  state.searchLoading = true;
  state.searchError = "";
  state.searchTime = null;
  state.results = [];
  state.answer = "";
  state.citations = [];

  const start = performance.now();

  try {
    if (state.mode === "search") {
      const res = await fetch(`${apiBase}/search`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: state.query, mode: "hybrid", filters: {}, page: 1, page_size: 10 }),
      });
      if (!res.ok) { state.searchError = `Search failed (${res.status})`; return; }
      const data = await res.json();
      state.results = data.results || [];
      if (state.results.length === 0) state.searchError = "No results found. Try different keywords.";
    } else {
      const res = await fetch(`${apiBase}/ask`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: state.query, filters: {}, top_k: 5 }),
      });
      if (!res.ok) { state.searchError = `Ask failed (${res.status})`; return; }
      const data = await res.json();
      state.answer = data.answer || "";
      state.citations = data.citations || [];
    }
  } catch (e: any) {
    state.searchError = `Error: ${e.message || "Could not reach server"}`;
  } finally {
    state.searchTime = Math.round(performance.now() - start);
    state.searchLoading = false;
  }
}

// -- Styles --

const css = `
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#f5f7fa;color:#1a1a2e}
.shell{max-width:860px;margin:0 auto;padding:32px 20px}
.header{text-align:center;margin-bottom:32px}
.header h1{font-size:1.6rem;font-weight:700;color:#1a1a2e}
.header p{color:#6b7280;font-size:.85rem;margin-top:4px}
.card{background:#fff;border-radius:12px;padding:20px 24px;margin-bottom:16px;box-shadow:0 1px 3px rgba(0,0,0,.06)}
.card h2{font-size:.8rem;text-transform:uppercase;letter-spacing:.06em;color:#9ca3af;margin-bottom:12px}
.search-row{display:flex;gap:8px;align-items:center}
.search-input{flex:1;padding:10px 14px;border:1.5px solid #e5e7eb;border-radius:8px;font-size:.95rem;outline:none;transition:border .15s}
.search-input:focus{border-color:#6366f1}
.btn{padding:10px 18px;border:none;border-radius:8px;font-size:.85rem;font-weight:600;cursor:pointer;transition:background .15s}
.btn-primary{background:#6366f1;color:#fff}
.btn-primary:hover:not(:disabled){background:#4f46e5}
.btn-primary:disabled{opacity:.6;cursor:not-allowed}
.btn-sm{padding:6px 12px;font-size:.78rem;border-radius:6px}
.btn-outline{background:transparent;border:1.5px solid #e5e7eb;color:#6b7280}
.btn-outline.active{border-color:#6366f1;color:#6366f1;background:#eef2ff}
.toggle-row{display:flex;gap:6px;margin-bottom:12px}
.upload-row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.upload-row input[type=file]{font-size:.85rem}
.upload-btn{cursor:pointer;display:inline-flex;align-items:center;gap:4px}
.status{font-size:.8rem;margin-top:8px}
.status-info{color:#6366f1}
.status-success{color:#16a34a}
.status-error{color:#dc2626}
.status-muted{color:#9ca3af}
.answer-box{background:#f0fdf4;border-left:3px solid #22c55e;padding:12px 16px;border-radius:6px;margin-bottom:12px;font-size:.9rem;line-height:1.5;white-space:pre-wrap}
.result-item{padding:12px 0;border-bottom:1px solid #f3f4f6}
.result-item:last-child{border-bottom:none}
.result-title{font-weight:600;font-size:.9rem;color:#1a1a2e;text-decoration:none;display:block}
.result-title:hover{color:#6366f1;text-decoration:underline}
.result-meta{font-size:.75rem;color:#9ca3af;margin-top:2px}
.result-snippet{font-size:.85rem;color:#4b5563;margin-top:6px;line-height:1.45}
.doc-list{list-style:none}
.doc-list li{padding:8px 0;border-bottom:1px solid #f3f4f6;font-size:.85rem;display:flex;justify-content:space-between;align-items:center}
.doc-list li:last-child{border-bottom:none}
.doc-title{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#1a1a2e;text-decoration:none}
.doc-title:hover{color:#6366f1;text-decoration:underline}
.doc-scroll{max-height:400px;overflow-y:auto}
.doc-category{border:1px solid #f3f4f6;border-radius:6px;margin-bottom:6px;overflow:hidden}
.doc-category-header{display:flex;align-items:center;gap:4px;padding:8px 10px;cursor:pointer;background:#fafafa;font-size:.82rem;font-weight:600;user-select:none}
.doc-category-header:hover{background:#f3f4f6}
.doc-category-name{flex:1}
.doc-category-count{background:#eef2ff;color:#6366f1;font-size:.7rem;font-weight:700;padding:1px 7px;border-radius:10px}
.doc-category .doc-list{margin:0;padding:0}
.doc-category .doc-list li{padding:6px 10px 6px 20px}
.btn-delete{background:none;border:none;color:#d1d5db;cursor:pointer;font-size:.85rem;padding:2px 6px;border-radius:4px;transition:color .15s,background .15s}
.btn-delete:hover{color:#dc2626;background:#fef2f2}
.btn-view{background:none;border:none;cursor:pointer;font-size:.85rem;padding:2px 4px}
.doc-text-viewer{margin-top:6px;padding:10px 12px;background:#f9fafb;border:1px solid #e5e7eb;border-radius:6px;font-size:.8rem;font-family:'Courier New',monospace;white-space:pre-wrap;word-break:break-word;max-height:300px;overflow-y:auto;color:#374151;line-height:1.5}
.btn-danger{background:#dc2626;color:#fff;border:none}
.btn-danger:hover{background:#b91c1c}
.badge{display:inline-block;padding:2px 8px;border-radius:4px;font-size:.7rem;font-weight:600;background:#eef2ff;color:#6366f1}
.badge-green{background:#f0fdf4;color:#16a34a}
.empty{color:#9ca3af;font-size:.85rem;text-align:center;padding:20px 0}
.search-meta{display:flex;gap:12px;align-items:center;margin-bottom:8px;font-size:.78rem;color:#9ca3af}
.spinner{display:inline-block;width:16px;height:16px;border:2px solid rgba(255,255,255,.3);border-top-color:#fff;border-radius:50%;animation:spin .6s linear infinite;margin-left:8px;vertical-align:middle}
@keyframes spin{to{transform:rotate(360deg)}}
.spinner-dark{border:2px solid #e5e7eb;border-top-color:#6366f1}
.settings-panel{font-size:.85rem}
.health-panel{margin-top:8px;font-size:.85rem}
.k8s-summary{display:flex;gap:20px;justify-content:center;padding:12px 0;margin-bottom:12px;border-bottom:1px solid #f3f4f6}
.k8s-stat{text-align:center}
.k8s-stat-value{font-size:1.5rem;font-weight:700;color:#1a1a2e}
.k8s-stat-label{font-size:.7rem;color:#9ca3af;text-transform:uppercase}
.k8s-running{color:#16a34a}
.k8s-pending{color:#f59e0b}
.k8s-failed{color:#dc2626}
.k8s-pods{display:flex;flex-direction:column;gap:6px}
.k8s-pod{border:1px solid #e5e7eb;border-radius:8px;padding:10px 12px;transition:border-color .15s}
.k8s-pod-ok{border-left:3px solid #16a34a}
.k8s-pod-err{border-left:3px solid #dc2626}
.k8s-pod-header{display:flex;align-items:center;gap:8px;cursor:pointer;user-select:none}
.k8s-pod-header:hover{opacity:.8}
.k8s-pod-icon{font-size:1.1rem}
.k8s-pod-component{font-weight:600;flex:1}
.k8s-pod-status{font-size:.75rem;padding:2px 8px;border-radius:10px;background:#f0fdf4;color:#16a34a}
.k8s-pod-status-err{background:#fef2f2;color:#dc2626}
.k8s-pod-toggle{color:#9ca3af;font-size:.7rem}
.k8s-pod-expanded{margin-top:8px;padding-top:8px;border-top:1px solid #f3f4f6}
.k8s-pod-table{width:100%;font-size:.78rem;border-collapse:collapse}
.k8s-pod-table td{padding:3px 8px;border-bottom:1px solid #f9fafb}
.k8s-pod-table td:first-child{color:#9ca3af;width:120px;font-weight:500}
.k8s-pod-table td:last-child{color:#374151}
.k8s-pod-details{display:flex;flex-wrap:wrap;gap:8px;margin-top:6px;font-size:.75rem;color:#6b7280}
.k8s-restarts{color:#f59e0b}
.k8s-events{margin-top:8px;border-top:1px solid #f3f4f6;padding-top:6px}
.k8s-events-toggle{font-size:.75rem;color:#6b7280;cursor:pointer;user-select:none;font-weight:500}
.k8s-events-toggle:hover{color:#374151}
.k8s-events-list{max-height:150px;overflow-y:auto;margin-top:4px;font-size:.72rem;font-family:'Courier New',monospace}
.k8s-event{display:grid;grid-template-columns:65px 120px 1fr;gap:8px;padding:3px 4px;border-bottom:1px solid #f3f4f6;align-items:start}
.k8s-event-time{color:#9ca3af}
.k8s-event-reason{color:#6366f1;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.k8s-event-msg{color:#374151;word-break:break-word}
.k8s-event-warn .k8s-event-reason{color:#f59e0b}
.k8s-event-warn .k8s-event-msg{color:#92400e}
.create-panel{margin-top:8px}
.create-model-info{display:flex;align-items:center;gap:6px;padding:8px 12px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;margin-bottom:10px;font-size:.78rem;color:#64748b}
.detect-bar{padding:6px 12px;border-radius:6px;font-size:.78rem;margin-bottom:8px;background:#f8fafc;border:1px solid #e2e8f0;display:flex;align-items:center}
.detect-loading{color:#6366f1}
.detect-accepted{color:#16a34a;display:flex;align-items:center;gap:4px}
.detect-rejected{color:#dc2626}
.detect-reject{background:none;border:none;cursor:pointer;color:#9ca3af;font-size:.85rem;margin-left:8px;padding:0 4px}
.detect-reject:hover{color:#dc2626}
.create-model-badge{font-size:1rem}
.create-model-hint{color:#94a3b8}
.create-textarea{width:100%;min-height:120px;padding:12px;border:1.5px solid #e5e7eb;border-radius:8px;font-size:.9rem;font-family:inherit;resize:vertical;outline:none;line-height:1.5}
.create-textarea:focus{border-color:#6366f1}
.create-controls{display:flex;gap:8px;align-items:center;margin-top:10px}
.create-source{margin-top:10px}
.create-source-label{font-size:.78rem;color:#6b7280;display:block;margin-bottom:4px}
.create-doc-picker{max-height:150px;overflow-y:auto;border:1px solid #e5e7eb;border-radius:6px;padding:6px}
.create-doc-option{display:flex;align-items:center;gap:6px;padding:3px 4px;font-size:.8rem;cursor:pointer;border-radius:4px}
.create-doc-option:hover{background:#f3f4f6}
.create-doc-option input{margin:0}
.create-preview{margin-top:12px;padding:14px;background:#f9fafb;border:1px solid #e5e7eb;border-radius:8px;font-size:.82rem;font-family:'Courier New',monospace;white-space:pre-wrap;word-break:break-word;max-height:400px;overflow-y:auto;line-height:1.5}
.create-img-preview{max-width:100%;border:1px solid #e5e7eb;border-radius:8px}
.create-pdf-preview{width:100%;height:500px;border:1px solid #e5e7eb;border-radius:8px}
.create-history{margin-top:12px;border-top:1px solid #f3f4f6;padding-top:10px}
.history-item{display:flex;align-items:center;gap:6px;padding:4px 0;font-size:.8rem;border-bottom:1px solid #f9fafb}
.history-prompt{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#374151}
.history-time{color:#9ca3af;font-size:.72rem;flex-shrink:0}
.collapsible{margin-bottom:10px;border:1px solid #f3f4f6;border-radius:8px;overflow:hidden}
.collapsible-header{padding:10px 12px;cursor:pointer;background:#fafafa;font-weight:600;font-size:.82rem;display:flex;align-items:center;gap:6px;user-select:none}
.collapsible-header:hover{background:#f3f4f6}
.collapsible-body{padding:12px}
.health-grid{display:flex;flex-direction:column;gap:4px}
.health-row{display:flex;align-items:center;gap:8px;padding:4px 0}
.health-icon{width:20px;text-align:center}
.health-name{font-weight:600;width:100px;text-transform:capitalize}
.health-detail{color:#6b7280;font-size:.8rem}
.error-console{margin-top:10px;background:#1a1a2e;color:#f87171;border-radius:6px;padding:10px 12px;font-family:'Courier New',monospace;font-size:.78rem;max-height:150px;overflow-y:auto}
.error-console-header{color:#9ca3af;margin-bottom:6px;font-size:.7rem;text-transform:uppercase;letter-spacing:.05em}
.error-line{padding:2px 0;word-break:break-all}
.config-row{display:flex;align-items:center;gap:8px;margin-bottom:8px}
.config-label{width:180px;font-size:.78rem;color:#6b7280;text-align:right;flex-shrink:0}
.config-input{flex:1;padding:6px 10px;border:1.5px solid #e5e7eb;border-radius:6px;font-size:.82rem;outline:none}
.config-input:focus{border-color:#6366f1}
.config-readonly{flex:1;padding:6px 10px;font-size:.82rem;color:#6b7280;background:#f9fafb;border-radius:6px;border:1px solid #f3f4f6}
.secret-field{display:flex;flex:1;gap:4px;align-items:center}
.secret-field .config-input{flex:1}
.btn-eye{background:none;border:none;cursor:pointer;font-size:1rem;padding:2px 4px}
.warning-banner{background:#fef3c7;border:1px solid #f59e0b;border-radius:8px;padding:10px 14px;margin-bottom:16px;font-size:.83rem;color:#92400e}
.warning-line{display:flex;align-items:center;gap:4px;padding:2px 0}
.usage-totals{display:flex;gap:16px;justify-content:center;padding:8px 0}
.usage-stat{text-align:center}
.usage-stat-value{font-size:1.2rem;font-weight:700;color:#1a1a2e}
.usage-stat-label{font-size:.7rem;color:#9ca3af;text-transform:uppercase;letter-spacing:.04em}
.usage-model-row{display:flex;justify-content:space-between;padding:3px 0;font-size:.8rem;border-bottom:1px solid #f9fafb}
.usage-model-name{color:#374151;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.usage-model-detail{color:#9ca3af;font-size:.75rem}
.usage-section{margin-top:10px}
.usage-scroll{max-height:200px;overflow-y:auto;border:1px solid #f3f4f6;border-radius:6px;padding:4px}
.usage-model-card{border-bottom:1px solid #f3f4f6}
.usage-model-card:last-child{border-bottom:none}
.usage-model-header{display:flex;align-items:center;gap:4px;padding:6px 4px;cursor:pointer;font-size:.8rem;user-select:none}
.usage-model-header:hover{background:#f9fafb}
.usage-model-summary{margin-left:auto;color:#6366f1;font-weight:600;font-size:.78rem}
.usage-model-detail-body{padding:4px 8px 8px 20px;font-size:.75rem;color:#6b7280;line-height:1.6}
.upload-log{margin-top:10px;max-height:250px;overflow-y:auto;font-size:.8rem;border:1px solid #f3f4f6;border-radius:8px;padding:6px}
.log-entry{display:flex;flex-direction:column;padding:3px 4px;border-bottom:1px solid #f9fafb}
.log-entry:last-child{border-bottom:none}
.log-entry-header{display:flex;gap:6px;align-items:center}
.log-icon{flex-shrink:0;width:18px;text-align:center}
.log-file{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#374151}
.log-detail{flex-shrink:0;color:#9ca3af;font-size:.75rem;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.log-expand{color:#9ca3af;font-size:.7rem;margin-left:4px}
.log-body{margin:4px 0 4px 24px;padding:4px 8px;background:#f9fafb;border-radius:4px;font-size:.73rem;color:#6b7280;font-family:'Courier New',monospace;max-height:120px;overflow-y:auto}
.log-line{padding:1px 0}
.log-uploading .log-file{color:#6366f1}
.log-done .log-detail{color:#16a34a}
.log-error .log-detail{color:#dc2626}
`;

// -- App --

createApp({
  setup() {
    loadDocuments();
    loadConfig();  // check model config on startup

    return () =>
      h("div", [
        h("style", css),
        h("div", { class: "shell" }, [

          // Header
          h("div", { class: "header" }, [
            h("h1", "📄 House Document Search"),
            h("p", "Upload, search, and ask questions about your documents"),
          ]),

          // Model warnings
          state.modelWarnings.length > 0
            ? h("div", { class: "warning-banner" },
                state.modelWarnings.map((w: string) =>
                  h("div", { class: "warning-line" }, [
                    h("span", "⚠️ "),
                    h("span", w),
                    h("button", {
                      class: "btn btn-sm btn-outline",
                      style: "margin-left:8px;padding:2px 8px",
                      onClick: () => { state.mode = "settings"; loadHealthCheck(); loadConfig(); },
                    }, "Settings"),
                  ]),
                ),
              )
            : null,

          // Search / Ask / Settings card
          h("div", { class: "card" }, [
            h("div", { class: "toggle-row" }, [
              h("button", {
                class: `btn btn-sm btn-outline ${state.mode === "search" ? "active" : ""}`,
                onClick: () => (state.mode = "search"),
              }, "Search"),
              h("button", {
                class: `btn btn-sm btn-outline ${state.mode === "ask" ? "active" : ""}`,
                onClick: () => (state.mode = "ask"),
              }, "Ask AI"),
              h("button", {
                class: `btn btn-sm btn-outline ${state.mode === "create" ? "active" : ""}`,
                onClick: () => { state.mode = "create"; loadConfig(); },
              }, "✏ Create"),
              h("button", {
                class: `btn btn-sm btn-outline ${state.mode === "health" ? "active" : ""}`,
                onClick: () => { state.mode = "health"; loadK8sHealth(); },
              }, "🏥 Health"),
              h("button", {
                class: `btn btn-sm btn-outline ${state.mode === "settings" ? "active" : ""}`,
                onClick: () => { state.mode = "settings"; loadHealthCheck(); loadConfig(); },
              }, "⚙ Settings"),
            ]),

            // Create panel
            state.mode === "create"
              ? h("div", { class: "create-panel" }, [
                  h("textarea", {
                    class: "create-textarea",
                    value: state.generatePrompt,
                    placeholder: "Describe the document you want to create...\n\nExample: Write a summary of all HOA fence and shed rules including height limits and approval requirements.",
                    onInput: (e: Event) => onPromptInput((e.target as HTMLTextAreaElement).value),
                    disabled: state.generateLoading,
                  }),
                  // Document source selector
                  h("div", { class: "create-source" }, [
                    h("label", { class: "create-source-label" },
                      state.generateSelectedDocs.length > 0
                        ? `Source: ${state.generateSelectedDocs.length} document${state.generateSelectedDocs.length === 1 ? "" : "s"} selected`
                        : "Source: auto-search (or pick specific documents below)",
                    ),
                    h("div", { class: "create-doc-picker" },
                      state.documents.map((d) =>
                        h("label", { class: "create-doc-option" }, [
                          h("input", {
                            type: "checkbox",
                            checked: state.generateSelectedDocs.includes(d.document_id),
                            onChange: () => {
                              if (state.generateSelectedDocs.includes(d.document_id)) {
                                state.generateSelectedDocs = state.generateSelectedDocs.filter((id: string) => id !== d.document_id);
                              } else {
                                state.generateSelectedDocs = [...state.generateSelectedDocs, d.document_id];
                              }
                            },
                          }),
                          h("span", d.title),
                        ]),
                      ),
                    ),
                  ]),
                  // Format detection status bar
                  (state.detectedFormat || state.detectingFormat)
                    ? h("div", { class: "detect-bar" }, [
                        state.detectingFormat
                          ? h("span", { class: "detect-loading" }, "Detecting format...")
                          : state.detectedAccepted === true
                            ? h("span", { class: "detect-accepted" }, [
                                "✅ ",
                                `Detected: ${({md:"Markdown",docx:"Word",pdf:"PDF",png:"Image",pptx:"PowerPoint"} as any)[state.detectedFormat]} — ${state.detectedReason}`,
                                h("button", {
                                  class: "detect-reject",
                                  title: "Override",
                                  onClick: () => { state.detectedAccepted = false; },
                                }, "✕"),
                              ])
                            : state.detectedAccepted === false
                              ? h("span", { class: "detect-rejected" }, "❌ Overridden — pick format manually below")
                              : null,
                      ])
                    : null,
                  h("div", { class: "create-controls" }, [
                    h("select", {
                      class: "config-input",
                      style: "width:auto",
                      value: state.generateFormat,
                      onChange: (e: Event) => {
                        state.generateFormat = (e.target as HTMLSelectElement).value;
                      },
                    }, [
                      h("option", { value: "md" }, "Markdown (.md)"),
                      h("option", { value: "docx" }, "Word (.docx)"),
                      h("option", { value: "pdf" }, "PDF (.pdf)"),
                      h("option", { value: "png" }, "Image (.png)"),
                      h("option", { value: "pptx" }, "PowerPoint (.pptx)"),
                    ]),
                    h("button", {
                      class: "btn btn-primary",
                      disabled: state.generateLoading || !state.generatePrompt.trim(),
                      onClick: generateDoc,
                    }, [
                      state.generateLoading ? "Generating..." : "Generate",
                      state.generateLoading ? h("span", { class: "spinner" }) : null,
                    ]),
                    state.generateDone
                      ? h("button", {
                          class: "btn btn-outline",
                          onClick: () => { (state as any).showPreview = !(state as any).showPreview; },
                        }, (state as any).showPreview ? "Hide Preview" : "Preview")
                      : null,
                    state.generateDone
                      ? h("button", {
                          class: "btn btn-primary btn-sm",
                          disabled: state.generateDownloading,
                          onClick: () => downloadGenerated(),
                        }, [
                          state.generateDownloading ? "Converting..." : `Download .${state.generateFormat}`,
                          state.generateDownloading ? h("span", { class: "spinner" }) : null,
                        ])
                      : null,
                  ]),
                  state.generateError
                    ? h("div", { class: "status status-error", style: "margin-top:8px" }, state.generateError)
                    : null,
                  // Preview (toggled)
                  state.generateDone && (state as any).showPreview
                    ? h("div", { class: "create-preview" }, state.generateResult)
                    : null,
                  // History
                  state.generateHistory.length > 1
                    ? h("div", { class: "create-history" }, [
                        h("div", { style: "font-weight:600;font-size:.78rem;color:#9ca3af;margin-bottom:4px" }, "Previous Generations"),
                        ...state.generateHistory.slice(1).map((item: any) =>
                          h("div", { class: "history-item" }, [
                            h("span", { class: "badge", style: "font-size:.65rem;margin-right:4px" }, (item.format || "md").toUpperCase()),
                            h("span", { class: "history-prompt" }, item.prompt),
                            h("span", { class: "history-time" }, item.timestamp),
                            h("button", {
                              class: "btn-view",
                              title: "Load this generation",
                              onClick: () => {
                                state.generateResult = item.markdown;
                                state.generateDone = true;
                                (state as any).showPreview = true;
                              },
                            }, "↩"),
                            h("button", {
                              class: "btn-view",
                              title: "Download",
                              onClick: () => downloadGenerated(item.markdown),
                            }, "⬇"),
                          ]),
                        ),
                      ])
                    : null,
                ])
              : null,

            // Health panel (k8s pod status)
            state.mode === "health"
              ? h("div", { class: "health-panel" }, [
                  state.k8sLoading
                    ? h("div", { class: "status status-info" }, "Loading cluster health...")
                    : null,
                  state.k8sHealth && !state.k8sHealth.available
                    ? h("div", { class: "status status-muted" }, `Kubernetes not available: ${state.k8sHealth.error || "cluster unreachable"}`)
                    : null,
                  state.k8sHealth && state.k8sHealth.available
                    ? h("div", [
                        // Summary bar
                        h("div", { class: "k8s-summary" }, [
                          h("div", { class: "k8s-stat" }, [
                            h("div", { class: "k8s-stat-value k8s-running" }, `${state.k8sHealth.summary.running}`),
                            h("div", { class: "k8s-stat-label" }, "Running"),
                          ]),
                          h("div", { class: "k8s-stat" }, [
                            h("div", { class: "k8s-stat-value" }, `${state.k8sHealth.summary.total}`),
                            h("div", { class: "k8s-stat-label" }, "Total Pods"),
                          ]),
                          state.k8sHealth.summary.pending > 0
                            ? h("div", { class: "k8s-stat" }, [
                                h("div", { class: "k8s-stat-value k8s-pending" }, `${state.k8sHealth.summary.pending}`),
                                h("div", { class: "k8s-stat-label" }, "Pending"),
                              ])
                            : null,
                          state.k8sHealth.summary.failed > 0
                            ? h("div", { class: "k8s-stat" }, [
                                h("div", { class: "k8s-stat-value k8s-failed" }, `${state.k8sHealth.summary.failed}`),
                                h("div", { class: "k8s-stat-label" }, "Failed"),
                              ])
                            : null,
                        ]),
                        // Pod cards (collapsible)
                        h("div", { class: "k8s-pods" },
                          state.k8sHealth.pods.map((pod: any) => {
                            const key = `pod_${pod.name}`;
                            const open = (state as any)[key];
                            return h("div", { class: `k8s-pod ${pod.status === "Running" ? "k8s-pod-ok" : "k8s-pod-err"}` }, [
                              h("div", {
                                class: "k8s-pod-header",
                                onClick: () => ((state as any)[key] = !open),
                              }, [
                                h("span", { class: "k8s-pod-icon" }, pod.icon),
                                h("span", { class: "k8s-pod-component" }, pod.component),
                                h("span", { class: `k8s-pod-status ${pod.status === "Running" ? "" : "k8s-pod-status-err"}` }, pod.status),
                                h("span", { class: "k8s-pod-toggle" }, open ? "▼" : "▶"),
                              ]),
                              open ? h("div", { class: "k8s-pod-expanded" }, [
                                h("table", { class: "k8s-pod-table" }, [
                                  h("tbody", [
                                    h("tr", [h("td", "Pod"), h("td", pod.name)]),
                                    h("tr", [h("td", "Node"), h("td", pod.node || "—")]),
                                    h("tr", [h("td", "Age"), h("td", pod.age || "—")]),
                                    h("tr", [h("td", "Restarts"), h("td", `${pod.restarts}`)]),
                                    h("tr", [h("td", "CPU Usage"), h("td", pod.cpu_usage || "—")]),
                                    h("tr", [h("td", "CPU Request"), h("td", pod.cpu || "—")]),
                                    h("tr", [h("td", "Memory Usage"), h("td", pod.memory_usage || "—")]),
                                    h("tr", [h("td", "Memory Request"), h("td", pod.memory || "—")]),
                                    h("tr", [h("td", "Disk (PVC)"), h("td", pod.disk || "—")]),
                                    h("tr", [h("td", "Image"), h("td", pod.image || "—")]),
                                    h("tr", [h("td", "Image Hash"), h("td", pod.image_hash || "—")]),
                                    h("tr", [h("td", "Started"), h("td", pod.started_at || "—")]),
                                  ]),
                                ]),
                                // Event history dropdown
                                pod.events && pod.events.length > 0
                                  ? h("div", { class: "k8s-events" }, [
                                      h("div", {
                                        class: "k8s-events-toggle",
                                        onClick: () => ((state as any)[`ev_${pod.name}`] = !(state as any)[`ev_${pod.name}`]),
                                      }, [
                                        h("span", (state as any)[`ev_${pod.name}`] ? "▼" : "▶"),
                                        h("span", ` Event History (${pod.events.length})`),
                                      ]),
                                      (state as any)[`ev_${pod.name}`]
                                        ? h("div", { class: "k8s-events-list" },
                                            pod.events.map((ev: any) =>
                                              h("div", { class: `k8s-event k8s-event-${ev.type === "Normal" ? "normal" : "warn"}` }, [
                                                h("span", { class: "k8s-event-time" }, ev.time),
                                                h("span", { class: "k8s-event-reason" }, ev.reason),
                                                h("span", { class: "k8s-event-msg" }, ev.message),
                                              ]),
                                            ),
                                          )
                                        : null,
                                    ])
                                  : null,
                              ]) : null,
                            ]);
                          }),
                        ),
                        h("button", {
                          class: "btn btn-sm btn-outline",
                          style: "margin-top:10px",
                          onClick: loadK8sHealth,
                        }, "Refresh"),
                      ])
                    : null,
                ])
              : null,

            // Settings panel
            state.mode === "settings"
              ? h("div", { class: "settings-panel" }, [

                  // Health section (collapsible)
                  h("div", { class: "collapsible" }, [
                    h("div", {
                      class: "collapsible-header",
                      onClick: () => (state.healthOpen = !state.healthOpen),
                    }, [
                      h("span", state.healthOpen ? "▼" : "▶"),
                      h("span", " Service Health"),
                      state.healthLoading ? h("span", { class: "spinner spinner-dark", style: "margin-left:8px" }) : null,
                    ]),
                    state.healthOpen ? h("div", { class: "collapsible-body" }, [
                      state.healthChecks
                        ? h("div", { class: "health-grid" },
                            Object.entries(state.healthChecks).map(([name, info]: [string, any]) =>
                              h("div", { class: `health-row health-${info.status === "ok" ? "ok" : "err"}` }, [
                                h("span", { class: "health-icon" }, info.status === "ok" ? "✅" : info.status === "not configured" ? "⚪" : "❌"),
                                h("span", { class: "health-name" }, name),
                                h("span", { class: "health-detail" },
                                  info.status === "not configured"
                                    ? "not configured"
                                    : info.status === "error"
                                      ? "connection failed"
                                      : name === "aws"
                                        ? `${info.version} · ${info.username} (${info.region})`
                                        : info.version || "connected",
                                ),
                              ]),
                            ),
                          )
                        : h("div", { class: "status status-muted" }, "Click to load..."),
                      // Error console
                      state.healthErrors.length > 0
                        ? h("div", { class: "error-console" }, [
                            h("div", { class: "error-console-header" }, "Errors"),
                            ...state.healthErrors.map((err: string) =>
                              h("div", { class: "error-line" }, `$ ${err}`),
                            ),
                            // Reindex button if search index is out of sync
                            state.healthChecks && state.healthChecks.search_index && state.healthChecks.search_index.status !== "ok"
                              ? h("button", {
                                  class: "btn btn-sm btn-primary",
                                  style: "margin-top:8px",
                                  onClick: async () => {
                                    const resp = await fetch(`${apiBase}/admin/reindex`, { method: "POST" });
                                    if (resp.ok) { await loadHealthCheck(); }
                                  },
                                }, "Reindex Now")
                              : null,
                          ])
                        : null,
                    ]) : null,
                  ]),

                  // Config section (collapsible)
                  h("div", { class: "collapsible" }, [
                    h("div", {
                      class: "collapsible-header",
                      onClick: () => { state.configOpen = !state.configOpen; if (state.configOpen) loadConfig(); },
                    }, [
                      h("span", state.configOpen ? "▼" : "▶"),
                      h("span", " Configuration"),
                    ]),
                    state.configOpen ? h("div", { class: "collapsible-body" }, [
                      ...Object.entries(state.configEdits).map(([key, val]: [string, string]) => {
                        const isSecret = key.includes("SECRET") || key.includes("API_TOKEN");
                        const isReadOnly = key === "WORKER_CONCURRENCY" || key === "MAX_WORKER_CONCURRENCY" || key === "OPENSEARCH_HOST" || key === "OPENSEARCH_PORT";
                        const isModelSelect = key === "BEDROCK_MODEL_ID" || key === "BEDROCK_GENERATE_MODEL_ID" || key === "BEDROCK_DETECT_MODEL_ID" || key === "BEDROCK_VISION_MODEL_ID";
                        const isRegionSelect = key === "AWS_REGION";
                        const models = key === "BEDROCK_VISION_MODEL_ID" ? state.visionModels : state.qaModels;

                        return h("div", { class: "config-row" }, [
                          h("label", { class: "config-label" }, ({
                            "BEDROCK_MODEL_ID": "Ask AI Model",
                            "BEDROCK_GENERATE_MODEL_ID": "Create Document Model",
                            "BEDROCK_DETECT_MODEL_ID": "Format Detection Model",
                            "BEDROCK_VISION_MODEL_ID": "Vision OCR Model",
                            "AWS_REGION": "AWS Region",
                            "BOOKSTACK_URL": "BookStack URL",
                            "BOOKSTACK_TOKEN_ID": "BookStack Token ID",
                            "BOOKSTACK_TOKEN_SECRET": "BookStack Secret",
                            "CONFLUENCE_URL": "Confluence URL",
                            "CONFLUENCE_EMAIL": "Confluence Email",
                            "CONFLUENCE_API_TOKEN": "Confluence Token",
                            "TRACK_USAGE": "Track Usage & Cost",
                            "WORKER_CONCURRENCY": "Upload Concurrency",
                            "OPENSEARCH_HOST": "OpenSearch Host",
                            "OPENSEARCH_PORT": "OpenSearch Port",
                          } as Record<string, string>)[key] || key),
                          isReadOnly
                            ? h("span", { class: "config-readonly" }, val || "—")
                            : isRegionSelect
                            ? h("select", {
                                class: "config-input",
                                value: val,
                                onChange: (e: Event) => (state.configEdits[key] = (e.target as HTMLSelectElement).value),
                              }, [
                                "us-east-1", "us-east-2", "us-west-2", "eu-west-1", "ap-southeast-1",
                              ].map(r => h("option", { value: r, selected: r === val }, r)))
                            : isModelSelect
                              ? h("select", {
                                  class: "config-input",
                                  value: val,
                                  onChange: (e: Event) => (state.configEdits[key] = (e.target as HTMLSelectElement).value),
                                }, models.map((m: any) => h("option", { value: m.id, selected: m.id === val }, m.label)))
                              : isSecret
                                ? h("div", { class: "secret-field" }, [
                                    h("input", {
                                      class: "config-input",
                                      type: (state as any)[`show_${key}`] ? "text" : "password",
                                      value: val,
                                      onInput: (e: Event) => (state.configEdits[key] = (e.target as HTMLInputElement).value),
                                    }),
                                    h("button", {
                                      class: "btn-eye",
                                      onClick: () => ((state as any)[`show_${key}`] = !(state as any)[`show_${key}`]),
                                      title: "Toggle visibility",
                                    }, (state as any)[`show_${key}`] ? "🙈" : "👁"),
                                  ])
                                : h("input", {
                                    class: "config-input",
                                    value: val,
                                    onInput: (e: Event) => (state.configEdits[key] = (e.target as HTMLInputElement).value),
                                  }),
                        ]);
                      }),
                      h("button", {
                        class: "btn btn-primary btn-sm",
                        style: "margin-top:10px",
                        onClick: saveConfig,
                      }, "Save"),
                      // Region/pricing info
                      h("div", { class: "status status-muted", style: "margin-top:8px;font-size:.75rem" },
                        `Pricing is pulled live from AWS for the selected region. Change the region above and Save to update pricing.`,
                      ),
                    ]) : null,
                  ]),

                  // Usage section (collapsible)
                  h("div", { class: "collapsible" }, [
                    h("div", {
                      class: "collapsible-header",
                      onClick: () => { state.usageOpen = !state.usageOpen; if (state.usageOpen) loadUsage(); },
                    }, [
                      h("span", state.usageOpen ? "▼" : "▶"),
                      h("span", " Token Usage & Cost"),
                    ]),
                    state.usageOpen && state.usageData ? h("div", { class: "collapsible-body" }, [
                      // Totals
                      h("div", { class: "usage-totals" }, [
                        h("div", { class: "usage-stat" }, [
                          h("div", { class: "usage-stat-value" }, `${(state.usageData.totals.total_input + state.usageData.totals.total_output).toLocaleString()}`),
                          h("div", { class: "usage-stat-label" }, "Total Tokens"),
                        ]),
                        h("div", { class: "usage-stat" }, [
                          h("div", { class: "usage-stat-value" }, `$${Number(state.usageData.totals.total_cost).toFixed(4)}`),
                          h("div", { class: "usage-stat-label" }, "Est. Cost"),
                        ]),
                        h("div", { class: "usage-stat" }, [
                          h("div", { class: "usage-stat-value" }, `${state.usageData.totals.total_calls}`),
                          h("div", { class: "usage-stat-label" }, "API Calls"),
                        ]),
                      ]),
                      // By model (each collapsible, scrollable container)
                      state.usageData.by_model.length > 0
                        ? h("div", { class: "usage-section" }, [
                            h("div", { style: "font-weight:600;font-size:.78rem;color:#9ca3af;margin-bottom:4px" }, "By Model"),
                            h("div", { class: "usage-scroll" },
                              state.usageData.by_model.map((m: any) => {
                                const key = `model_${m.model_id}`;
                                const open = (state as any)[key];
                                const shortName = m.model_id.replace("anthropic.", "").replace("amazon.", "").replace("meta.", "").replace("mistral.", "");
                                return h("div", { class: "usage-model-card" }, [
                                  h("div", {
                                    class: "usage-model-header",
                                    onClick: () => ((state as any)[key] = !open),
                                  }, [
                                    h("span", open ? "▼ " : "▶ "),
                                    h("span", { class: "usage-model-name" }, shortName),
                                    h("span", { class: "usage-model-summary" }, `$${Number(m.cost).toFixed(4)}`),
                                  ]),
                                  open ? h("div", { class: "usage-model-detail-body" }, [
                                    h("div", `Calls: ${m.calls}`),
                                    h("div", `Input tokens: ${Number(m.input_tokens).toLocaleString()}`),
                                    h("div", `Output tokens: ${Number(m.output_tokens).toLocaleString()}`),
                                    h("div", `Total tokens: ${(Number(m.input_tokens) + Number(m.output_tokens)).toLocaleString()}`),
                                    h("div", `Estimated cost: $${Number(m.cost).toFixed(6)}`),
                                  ]) : null,
                                ]);
                              }),
                            ),
                          ])
                        : null,
                      // By day (scrollable)
                      state.usageData.by_day.length > 0
                        ? h("div", { class: "usage-section" }, [
                            h("div", { style: "font-weight:600;font-size:.78rem;color:#9ca3af;margin-bottom:4px" }, "Last 30 Days"),
                            h("div", { class: "usage-scroll" },
                              state.usageData.by_day.map((d: any) =>
                                h("div", { class: "usage-model-row" }, [
                                  h("span", { class: "usage-model-name" }, String(d.day)),
                                  h("span", { class: "usage-model-detail" }, `${d.calls} calls · ${(Number(d.input_tokens) + Number(d.output_tokens)).toLocaleString()} tokens · $${Number(d.cost).toFixed(4)}`),
                                ]),
                              ),
                            ),
                          ])
                        : null,
                      h("button", {
                        class: "btn btn-sm btn-outline",
                        style: "margin-top:8px",
                        onClick: loadUsage,
                      }, "Refresh"),
                    ]) : state.usageOpen ? h("div", { class: "collapsible-body status status-muted" }, "Loading...") : null,
                  ]),
                ])
              : null,

            // Search/Ask input (hidden in settings mode)
            state.mode !== "settings" && state.mode !== "create" && state.mode !== "health" ? h("div", { class: "search-row" }, [
              h("input", {
                class: "search-input",
                value: state.query,
                disabled: state.searchLoading,
                placeholder: state.mode === "search"
                  ? "Search documents..."
                  : "Ask a question about your documents...",
                onInput: (e: Event) => (state.query = (e.target as HTMLInputElement).value),
                onKeydown: (e: KeyboardEvent) => {
                  if (e.key === "Enter" && !state.searchLoading) submit();
                },
              }),
              h("button", {
                class: "btn btn-primary",
                disabled: state.searchLoading,
                onClick: submit,
              }, [
                state.searchLoading
                  ? "Searching..."
                  : (state.mode === "search" ? "Search" : "Ask"),
                state.searchLoading ? h("span", { class: "spinner" }) : null,
              ]),
            ]) : null,
          ]),

          // Results card (hidden in settings mode)
          state.mode !== "settings" && state.mode !== "create" && state.mode !== "health" && (hasResults.value || state.searchError || state.searchTime !== null)
            ? h("div", { class: "card" }, [
                h("h2", "Results"),
                state.searchTime !== null
                  ? h("div", { class: "search-meta" }, [
                      state.results.length > 0
                        ? `${state.results.length} result${state.results.length === 1 ? "" : "s"}`
                        : null,
                      state.citations.length > 0
                        ? `${state.citations.length} citation${state.citations.length === 1 ? "" : "s"}`
                        : null,
                      `${state.searchTime}ms`,
                    ].filter(Boolean).join(" · "))
                  : null,
                state.searchError
                  ? h("div", { class: "status status-muted", style: "text-align:center;padding:12px 0;" }, state.searchError)
                  : null,
                state.answer
                  ? h("div", { class: "answer-box" }, state.answer)
                  : null,
                ...(state.mode === "ask" ? state.citations : state.results).map((r: any) =>
                  h("div", { class: "result-item" }, [
                    h("a", {
                      class: "result-title",
                      href: `${apiBase}/documents/${r.document_id}/file`,
                      target: "_blank",
                      title: "Open document",
                    }, r.title),
                    h("div", { class: "result-meta" }, [
                      r.document_type ? h("span", { class: "badge" }, r.document_type) : null,
                      r.score != null ? ` · score ${r.score}` : null,
                    ]),
                    h("div", { class: "result-snippet" }, r.snippet),
                  ])
                ),
              ])
            : null,

          // Upload card (files or folders - accumulates selections)
          h("div", { class: "card" }, [
            h("h2", "Upload Documents"),
            h("div", { class: "upload-row" }, [
              h("label", { class: "btn btn-sm btn-outline upload-btn" }, [
                "📄 Add Files",
                h("input", {
                  type: "file",
                  accept: ".pdf,.docx,.doc,.txt,.md,.jpg,.jpeg,.png,.tiff,.tif",
                  multiple: true,
                  disabled: state.uploadLoading,
                  style: "display:none",
                  onChange: (e: Event) => {
                    const files = (e.target as HTMLInputElement).files;
                    if (files) state.uploadFiles = [...state.uploadFiles, ...Array.from(files)];
                    (e.target as HTMLInputElement).value = "";
                  },
                }),
              ]),
              h("label", { class: "btn btn-sm btn-outline upload-btn" }, [
                "📁 Add Folder",
                h("input", {
                  type: "file",
                  webkitdirectory: true,
                  multiple: true,
                  disabled: state.uploadLoading,
                  style: "display:none",
                  onChange: (e: Event) => {
                    const files = (e.target as HTMLInputElement).files;
                    if (files) state.uploadFiles = [...state.uploadFiles, ...Array.from(files)];
                    (e.target as HTMLInputElement).value = "";
                  },
                }),
              ]),
              state.uploadFiles.length > 0 && !state.uploadLoading
                ? h("button", {
                    class: "btn btn-sm btn-outline",
                    onClick: () => { state.uploadFiles = []; },
                    title: "Clear selection",
                  }, "✕ Clear")
                : null,
              h("button", {
                class: "btn btn-primary btn-sm",
                disabled: state.uploadLoading || state.uploadFiles.length === 0,
                onClick: upload,
              }, [
                state.uploadLoading
                  ? "Processing..."
                  : `Upload${state.uploadFiles.length > 0 ? ` (${state.uploadFiles.length} files)` : ""}`,
                state.uploadLoading ? h("span", { class: "spinner" }) : null,
              ]),
              // Cancel button (visible during upload)
              state.uploadLoading
                ? h("button", {
                    class: "btn btn-sm btn-danger",
                    onClick: async () => {
                      await fetch(`${apiBase}/admin/cancel-upload`, { method: "POST" });
                      state.uploadLoading = false;
                      state.uploadStatus = "Upload cancelled";
                    },
                  }, "✕ Cancel")
                : null,
            ]),
            state.uploadFiles.length > 0 && !state.uploadLoading
              ? h("div", { class: "status status-info", style: "margin-top:6px" },
                  `${state.uploadFiles.length} file${state.uploadFiles.length === 1 ? "" : "s"} queued. Click "Add Folder" again to add more folders.`)
              : null,
            // Live progress log with expandable processing details
            state.uploadLog.length > 0
              ? h("div", { class: "upload-log" },
                  state.uploadLog.map((entry: any, idx: number) => {
                    const logKey = `log_open_${idx}`;
                    const isOpen = (state as any)[logKey];
                    return h("div", { class: `log-entry log-${entry.status}` }, [
                      h("div", {
                        class: "log-entry-header",
                        onClick: () => { if (entry.log && entry.log.length) (state as any)[logKey] = !isOpen; },
                        style: entry.log && entry.log.length ? "cursor:pointer" : "",
                      }, [
                        h("span", { class: "log-icon" },
                          entry.status === "uploading" ? "⏳" : entry.status === "done" ? "✅" : "❌"),
                        h("span", { class: "log-file" }, entry.file),
                        h("span", { class: "log-detail" }, entry.detail),
                        entry.log && entry.log.length
                          ? h("span", { class: "log-expand" }, isOpen ? "▼" : "▶")
                          : null,
                      ]),
                      isOpen && entry.log
                        ? h("div", { class: "log-body" },
                            entry.log.map((line: string) => h("div", { class: "log-line" }, line)),
                          )
                        : null,
                    ]);
                  }),
                )
              : null,
            state.uploadStatus
              ? h("div", {
                  class: `status ${state.uploadStatus.includes("error") || state.uploadStatus.includes("fail") ? "status-error" : "status-success"}`,
                  style: "margin-top:8px",
                }, state.uploadStatus)
              : null,
          ]),

          // Documents list - grouped by category, collapsible, scrollable
          h("div", { class: "card" }, [
            h("div", { style: "display:flex;justify-content:space-between;align-items:center;margin-bottom:12px" }, [
              h("h2", { style: "margin-bottom:0" }, `Documents (${state.documents.length})`),
              state.documents.length > 0
                ? h("button", { class: "btn btn-sm btn-danger", onClick: deleteAll }, "Clear All")
                : null,
            ]),
            state.documents.length === 0
              ? h("div", { class: "empty" }, "No documents uploaded yet")
              : h("div", { class: "doc-scroll" },
                  // Group by category
                  Object.entries(
                    state.documents.reduce((acc: Record<string, typeof state.documents>, d) => {
                      const cat = (d as any).category || "Uncategorized";
                      (acc[cat] = acc[cat] || []).push(d);
                      return acc;
                    }, {} as Record<string, typeof state.documents>),
                  )
                    .sort(([a], [b]) => a.localeCompare(b))
                    .map(([category, docs]) => {
                      const key = `cat_${category}`;
                      const open = (state as any)[key] !== false; // default open
                      return h("div", { class: "doc-category" }, [
                        h("div", {
                          class: "doc-category-header",
                          onClick: () => ((state as any)[key] = !open),
                        }, [
                          h("span", open ? "▼ " : "▶ "),
                          h("span", { class: "doc-category-name" }, category),
                          h("span", { class: "doc-category-count" }, `${docs.length}`),
                        ]),
                        open
                          ? h("ul", { class: "doc-list" },
                              docs.map((d) =>
                                h("li", [
                                  h("a", {
                                    class: "doc-title",
                                    href: `${apiBase}/documents/${d.document_id}/file`,
                                    target: "_blank",
                                    title: "Open document",
                                  }, d.title),
                                  h("span", { style: "display:flex;gap:6px;align-items:center" }, [
                                    h("span", { class: "badge" }, d.document_type),
                                    h("span", {
                                      class: `badge ${d.status === "indexed" ? "badge-green" : ""}`,
                                    }, d.status),
                                    h("button", {
                                      class: "btn-view",
                                      title: "View extracted text",
                                      onClick: () => viewDoc(d.document_id),
                                    }, (state as any)[`view_${d.document_id}`] ? "🙈" : "👁"),
                                    h("button", {
                                      class: "btn-delete",
                                      title: "Delete",
                                      onClick: () => deleteDoc(d.document_id),
                                    }, "✕"),
                                  ]),
                                  (state as any)[`view_${d.document_id}`]
                                    ? h("div", { class: "doc-text-viewer" },
                                        (state as any)[`view_${d.document_id}`],
                                      )
                                    : null,
                                ]),
                              ),
                            )
                          : null,
                      ]);
                    }),
                ),
          ]),
        ]),
      ]);
  },
}).mount("#app");
