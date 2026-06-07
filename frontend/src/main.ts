/**
 * Document Search - Frontend
 *
 * Single-page Vue app for uploading house documents (PDFs, DOCX, etc.)
 * and searching or asking AI questions about their contents.
 */

import { createApp, h, reactive, computed } from "vue";
import { renderAsync } from "docx-preview";

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
  document_date: string | null;
  uploaded_at: string | null;
  original_filename: string;
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
  mode: "search" as "search" | "ask" | "create" | "tasks" | "templates" | "diagnostic" | "gap-email" | "settings",
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
  embeddingModels: [] as Array<{ id: string; label: string }>,
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
  generateHistory: [] as Array<{ prompt: string; markdown: string; format: string; timestamp: string }>,
  detectedFormat: "" as string,
  detectedReason: "" as string,
  detectedAccepted: null as boolean | null,
  detectingFormat: false,

  // Templates
  templates: [] as Array<{ template_id: string; name: string; source_format: string; created_at: string }>,
  selectedTemplateId: "" as string,
  templateImporting: false,
  templatePreview: null as any,

  // K8s Health
  k8sHealth: null as any,
  k8sLoading: false,
  k8sOpen: false,

  // Tasks
  taskPrompt: "",
  taskDocIds: [] as string[],
  taskHistory: [] as Array<{ role: string; content: string }>,
  taskResult: "",
  taskLoading: false,
  taskRefinement: "",
  taskStep: "prompt" as "prompt" | "review-docs" | "generating" | "result",
  taskFoundDocs: [] as Array<{ document_id: string; title: string; score: number; snippet: string }>,
  taskSearching: false,

  // Gap-to-Email
  gapFormDocId: "" as string,
  gapFormSearch: "" as string,
  gapFormDropdownOpen: false,
  gapContextDocIds: [] as string[],
  gapContextSearch: "" as string,
  gapContextDropdownOpen: false,
  gapVendors: [] as Array<{ name: string; contact: string; doc_ids: string[]; notes: string }>,
  gapExampleEmail: "",
  gapLoading: false,
  gapResults: [] as Array<{ vendor_name: string; contact: string; gaps: string[]; email: string }>,
  gapError: "",
  gapNewVendorName: "",
  gapNewVendorContact: "",
  gapNewVendorDocs: [] as string[],
  gapNewVendorNotes: "",
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

  const totalFiles = files.length;

  try {
    // Submit all files at once to the queue endpoint
    const body = new FormData();
    for (const file of files) body.append("files", file);

    state.uploadStatus = `Submitting ${totalFiles} files...`;
    const submitRes = await fetch(`${apiBase}/ingest/upload-queue`, { method: "POST", body });
    if (!submitRes.ok) {
      state.uploadStatus = `Submit failed: ${await submitRes.text()}`;
      return;
    }

    const { batch_id, queued } = await submitRes.json();
    state.uploadStatus = `${queued} files queued. Processing...`;

    // Initialize log entries
    for (const file of files) {
      state.uploadLog.push({ file: file.name, status: "uploading", detail: "queued" });
    }

    // Persist batch_id so we can reconnect after refresh
    localStorage.setItem("upload_batch_id", batch_id);
    localStorage.setItem("upload_total", String(totalFiles));

    // Subscribe to status stream
    await watchBatch(batch_id, totalFiles);
  } catch (e: any) {
    state.uploadStatus = `Upload error: ${e.message || "Could not reach server"}`;
  } finally {
    state.uploadLoading = false;
  }
}

async function watchBatch(batchId: string, totalFiles: number) {
  try {
    const res = await fetch(`${apiBase}/ingest/upload-status/${batchId}`);
    if (!res.ok) {
      state.uploadStatus = `Status stream failed: ${await res.text()}`;
      return;
    }

    const reader = res.body!.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let totalOk = 0;
    let totalFail = 0;

    while (true) {
      if (!state.uploadLoading) break;
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      const lines = buffer.split("\n");
      buffer = lines.pop() || "";
      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        const msg = JSON.parse(line.slice(6));

        if (msg.type === "done") {
          const idx = state.uploadLog.findIndex((l: any) => l.file === msg.file && l.status === "uploading");
          if (idx >= 0) {
            state.uploadLog[idx] = { file: msg.file, status: "done", detail: `${msg.category} / ${msg.document_type}` };
          } else {
            state.uploadLog.push({ file: msg.file, status: "done", detail: `${msg.category} / ${msg.document_type}` });
          }
          totalOk++;
          state.uploadStatus = `Progress: ${totalOk + totalFail}/${totalFiles} (${totalOk} ok, ${totalFail} failed)`;
        } else if (msg.type === "error") {
          const idx = state.uploadLog.findIndex((l: any) => l.file === msg.file && l.status === "uploading");
          if (idx >= 0) {
            state.uploadLog[idx] = { file: msg.file, status: "error", detail: msg.error };
          } else {
            state.uploadLog.push({ file: msg.file, status: "error", detail: msg.error });
          }
          totalFail++;
          state.uploadStatus = `Progress: ${totalOk + totalFail}/${totalFiles} (${totalOk} ok, ${totalFail} failed)`;
        } else if (msg.type === "complete") {
          state.uploadStatus = `Done: ${msg.uploaded} indexed, ${msg.errors} failed out of ${totalFiles}`;
          localStorage.removeItem("upload_batch_id");
          localStorage.removeItem("upload_total");
        }
      }
    }

    state.uploadFiles = [];
    const inputs = document.querySelectorAll('input[type="file"]') as NodeListOf<HTMLInputElement>;
    inputs.forEach(el => el.value = "");
    await loadDocuments();
  } catch (e: any) {
    state.uploadStatus = `Stream disconnected: ${e.message || "connection lost"} — refresh to reconnect`;
  } finally {
    state.uploadLoading = false;
  }
}

function resumeUploadIfNeeded() {
  const batchId = localStorage.getItem("upload_batch_id");
  const total = localStorage.getItem("upload_total");
  if (batchId && total) {
    state.uploadLoading = true;
    state.uploadStatus = "Reconnecting to in-progress upload...";
    watchBatch(batchId, parseInt(total, 10));
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

// -- Templates --

async function loadTemplates() {
  try {
    const resp = await fetch(`${apiBase}/templates`);
    if (resp.ok) state.templates = await resp.json();
  } catch { /* ignore */ }
}

async function importTemplate() {
  const input = document.createElement("input");
  input.type = "file";
  input.accept = ".pdf,.docx,.doc,.pptx,.md,.jpg,.jpeg,.png,.tiff,.tif";
  input.onchange = async () => {
    const file = input.files?.[0];
    if (!file) return;
    state.templateImporting = true;
    state.templatePreview = null;
    try {
      const form = new FormData();
      form.append("file", file);
      const resp = await fetch(`${apiBase}/templates/extract`, { method: "POST", body: form });
      if (!resp.ok) {
        const err = await resp.json();
        state.generateError = err.detail || "Template extraction failed";
        return;
      }
      const data = await resp.json();
      state.templatePreview = data.structure;
      state.selectedTemplateId = data.template_id;
      await loadTemplates();
    } catch (e: any) {
      state.generateError = e.message || "Template import failed";
    } finally {
      state.templateImporting = false;
    }
  };
  input.click();
}

async function deleteTemplate(id: string) {
  await fetch(`${apiBase}/templates/${id}`, { method: "DELETE" });
  if (state.selectedTemplateId === id) {
    state.selectedTemplateId = "";
    state.templatePreview = null;
  }
  await loadTemplates();
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
        template_id: state.selectedTemplateId || undefined,
      }),
    });
    if (!resp.ok) {
      const err = await resp.json();
      state.generateError = err.detail || "Generation failed";
      return;
    }
    const data = await resp.json();
    state.generateResult = data.markdown;
    const effectiveFormat = data.format || state.generateFormat;
    state.generateFormat = effectiveFormat;
    state.generateDone = true;
    // Save to history (skip if same prompt+format already exists)
    const isDuplicate = state.generateHistory.some(
      (h) => h.prompt === state.generatePrompt && h.format === effectiveFormat
    );
    if (!isDuplicate) {
      state.generateHistory.unshift({
        prompt: state.generatePrompt,
        markdown: data.markdown,
        format: effectiveFormat,
        timestamp: new Date().toLocaleTimeString(),
      });
      if (state.generateHistory.length > 10) state.generateHistory.pop();
    }
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

  if (fmt === "txt") {
    const plain = content
      .replace(/^#{1,6}\s+/gm, "")
      .replace(/\*\*([^*]+)\*\*/g, "$1")
      .replace(/\*([^*]+)\*/g, "$1")
      .replace(/^[-*]\s+/gm, "")
      .replace(/^---+$/gm, "")
      .replace(/\n{3,}/g, "\n\n")
      .trim();
    const blob = new Blob([plain], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = "generated.txt"; a.click();
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

async function runTask(refinement?: string) {
  state.taskLoading = true;
  (state as any).taskStatus = "";
  const prompt = refinement || state.taskPrompt;
  try {
    const resp = await fetch(`${apiBase}/tasks/generate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        prompt,
        document_ids: state.taskDocIds,
        history: state.taskHistory,
        format: "md",
        skip_auto_search: state.taskDocIds.length > 0,
      }),
    });
    const reader = resp.body!.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";
      for (const line of lines) {
        if (line.startsWith("data: ")) {
          try {
            const data = JSON.parse(line.slice(6));
            if (data.status) (state as any).taskStatus = data.status;
            if (data.error) { state.taskResult = `Error: ${data.error}`; state.taskStep = "result"; }
            if (data.result) {
              state.taskResult = data.result.markdown;
              state.taskHistory = data.result.history || [];
              state.taskStep = "result";
            }
          } catch { /* ignore parse errors */ }
        }
      }
    }
  } catch (e: any) {
    state.taskResult = `Error: ${e.message}`;
    state.taskStep = "result";
  }
  state.taskLoading = false;
  state.taskRefinement = "";
  (state as any).taskStatus = "";
}

function resetTask() {
  state.taskPrompt = "";
  state.taskDocIds = [];
  state.taskHistory = [];
  state.taskResult = "";
  state.taskRefinement = "";
  state.taskStep = "prompt";
  state.taskFoundDocs = [];
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
    state.embeddingModels = models.embedding || [];
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

function previewDoc(doc: DocInfo) {
  const ext = doc.title.split(".").pop()?.toLowerCase() || "";
  (state as any).previewDoc = doc;
  (state as any).previewExt = ext;
}

async function deleteDoc(id: string) {
  await fetch(`${apiBase}/documents/${id}`, { method: "DELETE" });
  await loadDocuments();
}

async function deleteAll() {
  if (!confirm(`Delete all ${state.documents.length} documents? This cannot be undone.`)) return;
  await fetch(`${apiBase}/documents`, { method: "DELETE" });
  localStorage.removeItem("upload_batch_id");
  localStorage.removeItem("upload_total");
  state.uploadLoading = false;
  state.uploadLog = [];
  state.uploadStatus = "";
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
.result-snippet{font-size:.85rem;color:#4b5563;margin-top:6px;line-height:1.45;padding:8px 12px;background:#f9fafb;border-radius:6px;border-left:3px solid #e5e7eb}
.result-snippet mark{background:#fef08a;padding:1px 2px;border-radius:2px}
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
.badge-date{background:#eff6ff;color:#2563eb}
.badge-upload{background:#f5f3ff;color:#7c3aed}
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
.preview-overlay{position:fixed;inset:0;background:rgba(0,0,0,.6);display:flex;align-items:center;justify-content:center;z-index:1000}
.preview-modal{background:#fff;border-radius:12px;width:90vw;max-width:900px;height:85vh;display:flex;flex-direction:column;overflow:hidden;box-shadow:0 20px 60px rgba(0,0,0,.3)}
.preview-header{display:flex;align-items:center;padding:12px 16px;border-bottom:1px solid #e5e7eb}
.preview-title{flex:1;font-size:.9rem;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.preview-close{background:none;border:none;font-size:1.3rem;cursor:pointer;padding:4px 8px;border-radius:4px;color:#6b7280}
.preview-close:hover{background:#f3f4f6;color:#1a1a2e}
.preview-body{flex:1;overflow:auto;padding:0}
.preview-body iframe{width:100%;height:100%;border:none}
.preview-body img{max-width:100%;max-height:100%;object-fit:contain;display:block;margin:0 auto}
.preview-docx{padding:20px;overflow:auto;height:100%}
`;

// -- App --

createApp({
  setup() {
    loadDocuments();
    loadConfig();  // check model config on startup
    resumeUploadIfNeeded();  // reconnect to in-progress batch after refresh

    return () =>
      h("div", [
        h("style", css),
        h("div", { class: "shell" }, [

          // Header
          h("div", { class: "header" }, [
            h("h1", "📄 Document Search"),
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
                class: `btn btn-sm btn-outline ${state.mode === "tasks" ? "active" : ""}`,
                onClick: () => { state.mode = "tasks"; },
              }, "🧠 Tasks"),
              h("button", {
                class: `btn btn-sm btn-outline ${state.mode === "templates" ? "active" : ""}`,
                onClick: () => { state.mode = "templates"; loadTemplates(); },
              }, "📋 Templates"),
              h("button", {
                class: `btn btn-sm btn-outline ${state.mode === "diagnostic" ? "active" : ""}`,
                onClick: () => { state.mode = "diagnostic"; loadTemplates(); },
              }, "🔬 Diagnostic"),
              h("button", {
                class: `btn btn-sm btn-outline ${state.mode === "gap-email" ? "active" : ""}`,
                onClick: () => { state.mode = "gap-email"; },
              }, "📧 Gap-to-Email"),
              h("button", {
                class: `btn btn-sm btn-outline ${state.mode === "settings" ? "active" : ""}`,
                onClick: () => { state.mode = "settings"; loadHealthCheck(); loadConfig(); loadK8sHealth(); },
              }, "⚙ Settings"),
            ]),


            // Tasks panel
            state.mode === "tasks"
              ? h("div", { class: "create-panel" }, [
                  h("div", { style: "display:flex;align-items:center;justify-content:space-between;margin-bottom:12px" }, [
                    h("h2", { style: "font-size:.85rem;text-transform:uppercase;letter-spacing:.06em;color:#9ca3af;margin:0" }, "Task Workflow"),
                    state.taskStep !== "prompt"
                      ? h("button", { class: "btn btn-sm btn-outline", onClick: resetTask }, "New Task")
                      : null,
                  ]),

                  // Step 1: Prompt
                  state.taskStep === "prompt"
                    ? h("div", [
                        h("textarea", { class: "create-textarea", placeholder: "Describe what you need (e.g., 'Write a description of proposed modification for the exterior modification form using American Home Contractors documents')...", value: state.taskPrompt, onInput: (e: any) => (state.taskPrompt = e.target.value), style: "min-height:100px" }),
                        h("button", {
                          class: "btn btn-primary", style: "margin-top:8px",
                          disabled: state.taskSearching || !state.taskPrompt.trim(),
                          onClick: async () => {
                            state.taskSearching = true;
                            try {
                              // Primary search on the full prompt
                              const res = await fetch(`${apiBase}/search`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ query: state.taskPrompt, mode: "hybrid", page: 1, page_size: 20 }) });
                              const data = await res.json();
                              const results = data.results || [];
                              const seen = new Set<string>();
                              const found: Array<{ document_id: string; title: string; score: number; snippet: string }> = [];
                              for (const r of results) {
                                if (!seen.has(r.document_id)) {
                                  seen.add(r.document_id);
                                  found.push({ document_id: r.document_id, title: r.title, score: r.score, snippet: (r.snippet || "").replace(/<\/?em>/g, "") });
                                }
                              }
                              // Extract capitalized entity names for follow-up searches
                              const entityMatch = state.taskPrompt.match(/[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+/g);
                              const searches: string[] = [];
                              if (entityMatch) {
                                for (const entity of entityMatch) {
                                  searches.push(entity);
                                  searches.push(`${entity} email correspondence reply`);
                                  // Also search abbreviation (e.g., "American Home Contractors" -> "AHC")
                                  const initials = entity.split(/\s+/).map((w: string) => w[0]).join("");
                                  if (initials.length >= 2) searches.push(`${initials} project`);
                                }
                              }
                              for (const q of searches) {
                                const res2 = await fetch(`${apiBase}/search`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ query: q, mode: "hybrid", page: 1, page_size: 15 }) });
                                const data2 = await res2.json();
                                for (const r of (data2.results || [])) {
                                  if (!seen.has(r.document_id)) {
                                    seen.add(r.document_id);
                                    found.push({ document_id: r.document_id, title: r.title, score: r.score, snippet: (r.snippet || "").replace(/<\/?em>/g, "") });
                                  }
                                }
                              }
                              state.taskFoundDocs = found;
                              state.taskDocIds = found.map((d: any) => d.document_id);
                              state.taskStep = "review-docs";
                            } catch (e: any) {
                              state.taskResult = `Error searching: ${e.message}`;
                            }
                            state.taskSearching = false;
                          },
                        }, state.taskSearching ? "Searching..." : "Find Documents →"),
                      ])
                    : null,

                  // Step 2: Review found documents
                  state.taskStep === "review-docs"
                    ? h("div", [
                        h("div", { style: "font-size:.8rem;color:#9ca3af;margin-bottom:8px" }, `Found ${state.taskFoundDocs.length} documents. Select which to use:`),
                        h("div", { style: "max-height:250px;overflow-y:auto;border:1px solid #374151;border-radius:6px;padding:6px;margin-bottom:10px" },
                          state.taskFoundDocs.map((d: any) =>
                            h("label", { style: "display:flex;align-items:flex-start;gap:8px;padding:6px;font-size:.8rem;cursor:pointer;color:#d1d5db;border-bottom:1px solid #1f2937;position:relative" }, [
                              h("input", {
                                type: "checkbox",
                                style: "margin-top:2px",
                                checked: state.taskDocIds.includes(d.document_id),
                                onChange: (e: any) => {
                                  if (e.target.checked) { state.taskDocIds = [...state.taskDocIds, d.document_id]; }
                                  else { state.taskDocIds = state.taskDocIds.filter((id: string) => id !== d.document_id); }
                                },
                              }),
                              h("div", { style: "flex:1;min-width:0" }, [
                                h("div", { style: "display:flex;justify-content:space-between;align-items:center" }, [
                                  h("span", { style: "font-weight:500" }, d.title),
                                  h("span", { style: "font-size:.65rem;color:#6b7280;white-space:nowrap;margin-left:8px" }, `${d.score.toFixed(1)}`),
                                ]),
                                d.snippet
                                  ? h("div", { style: "font-size:.7rem;color:#9ca3af;margin-top:3px;line-height:1.3;overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical" }, `"${d.snippet.slice(0, 200)}${d.snippet.length > 200 ? "..." : ""}"`)
                                  : null,
                              ]),
                            ])
                          ),
                        ),
                        h("div", { style: "font-size:.7rem;color:#6b7280;margin-bottom:8px" }, `${state.taskDocIds.length} selected`),
                        h("div", { style: "display:flex;gap:8px" }, [
                          h("button", { class: "btn btn-sm btn-outline", onClick: () => { state.taskStep = "prompt"; } }, "← Back"),
                          h("button", {
                            class: "btn btn-primary",
                            disabled: state.taskLoading || !state.taskDocIds.length,
                            onClick: () => { state.taskStep = "generating"; runTask(); },
                          }, "Generate →"),
                        ]),
                      ])
                    : null,

                  // Step 3: Generating (loading)
                  state.taskStep === "generating"
                    ? h("div", { style: "text-align:center;padding:20px" }, [
                        h("div", { class: "spinner spinner-dark", style: "margin:0 auto 10px" }),
                        (state as any).taskStatus ? h("div", { style: "font-size:.8rem;color:#6366f1" }, (state as any).taskStatus) : null,
                      ])
                    : null,

                  // Step 4: Result + refinement
                  state.taskStep === "result"
                    ? h("div", [
                        h("div", { style: "border:1px solid #374151;border-radius:8px;padding:12px;max-height:400px;overflow-y:auto;font-size:.82rem;white-space:pre-wrap;background:#111827;color:#d1d5db;margin-bottom:10px" }, state.taskResult),
                        h("div", { style: "display:flex;gap:8px;align-items:flex-end" }, [
                          h("textarea", { class: "create-textarea", placeholder: "Refine: e.g. 'Make it first person' or 'Add the plywood note'", value: state.taskRefinement, onInput: (e: any) => (state.taskRefinement = e.target.value), style: "min-height:60px;flex:1" }),
                          h("button", { class: "btn btn-primary", disabled: state.taskLoading || !state.taskRefinement.trim(), onClick: () => { state.taskStep = "generating"; runTask(state.taskRefinement); } }, state.taskLoading ? "..." : "Refine"),
                        ]),
                        (state as any).taskStatus ? h("div", { style: "margin-top:8px;font-size:.78rem;color:#6366f1;display:flex;align-items:center;gap:6px" }, [h("span", { class: "spinner spinner-dark" }), h("span", (state as any).taskStatus)]) : null,
                        h("div", { style: "display:flex;gap:8px;margin-top:10px" }, [
                          h("button", { class: "btn btn-sm btn-outline", onClick: async () => { const r = await fetch(`${apiBase}/generate/convert`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ markdown: state.taskResult, format: "pdf" }) }); const b = await r.blob(); const u = URL.createObjectURL(b); const a = document.createElement("a"); a.href = u; a.download = "task_output.pdf"; a.click(); } }, "📥 PDF"),
                          h("button", { class: "btn btn-sm btn-outline", onClick: async () => { const r = await fetch(`${apiBase}/generate/convert`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ markdown: state.taskResult, format: "docx" }) }); const b = await r.blob(); const u = URL.createObjectURL(b); const a = document.createElement("a"); a.href = u; a.download = "task_output.docx"; a.click(); } }, "📥 DOCX"),
                          h("button", { class: "btn btn-sm btn-outline", onClick: () => { const b = new Blob([state.taskResult], { type: "text/markdown" }); const u = URL.createObjectURL(b); const a = document.createElement("a"); a.href = u; a.download = "task_output.md"; a.click(); } }, "📥 Markdown"),
                          h("button", { class: "btn btn-sm btn-outline", onClick: async () => {
                            const r = await fetch(`${apiBase}/generate/export-package`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ markdown: state.taskResult, document_ids: state.taskDocIds, filename_prefix: "submission_package" }) });
                            const data = await r.json();
                            if (data.file_b64) { const bytes = Uint8Array.from(atob(data.file_b64), c => c.charCodeAt(0)); const blob = new Blob([bytes], { type: "application/zip" }); const u = URL.createObjectURL(blob); const a = document.createElement("a"); a.href = u; a.download = data.filename || "submission_package.zip"; a.click(); }
                          } }, "📦 Package (ZIP)"),
                        ]),
                        h("div", { style: "font-size:.7rem;color:#9ca3af;margin-top:8px" }, `${Math.floor(state.taskHistory.length / 2)} iteration(s)`),
                      ])
                    : null,
                ])
              : null,
            // Templates panel
            state.mode === "templates"
              ? h("div", { class: "create-panel" }, [
                  // Header with import button
                  h("div", { style: "display:flex;align-items:center;justify-content:space-between;margin-bottom:12px" }, [
                    h("h2", { style: "font-size:.85rem;text-transform:uppercase;letter-spacing:.06em;color:#9ca3af;margin:0" }, "Templates"),
                    h("button", {
                      class: "btn btn-sm btn-primary",
                      disabled: state.templateImporting,
                      onClick: importTemplate,
                    }, state.templateImporting ? "Importing..." : "+ Import Template"),
                  ]),
                  // Model quality note
                  h("div", { style: "background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:10px 14px;margin-bottom:12px;font-size:.78rem;color:#64748b;line-height:1.5" }, [
                    h("span", { style: "font-weight:600;color:#475569" }, "💡 Extraction quality depends on your Template model. "),
                    "A faster model (e.g. Haiku) works well for short documents but may miss details on longer ones (5+ pages). ",
                    "A larger model (e.g. Sonnet) captures full structure, fonts, and layout even for complex documents. ",
                    "Change the model in ",
                    h("span", { style: "color:#6366f1;cursor:pointer;text-decoration:underline", onClick: () => { state.mode = "settings"; loadConfig(); } }, "Settings → Template Extraction Model"),
                    ".",
                  ]),
                  // Template list
                  state.templates.length === 0
                    ? h("div", { class: "empty" }, "No templates yet. Import a PDF, DOCX, or PPTX to extract its structure.")
                    : h("div", { style: "display:flex;flex-direction:column;gap:8px;max-height:240px;overflow-y:auto;border:1px solid #f3f4f6;border-radius:8px;padding:8px" },
                        state.templates.map((t: any) =>
                          h("div", {
                            style: `border:1px solid ${state.selectedTemplateId === t.template_id ? "#6366f1" : "#e5e7eb"};border-radius:8px;padding:10px 14px;cursor:pointer;transition:border-color .15s`,
                            onClick: async () => {
                              if (state.selectedTemplateId === t.template_id) {
                                state.selectedTemplateId = "";
                                state.templatePreview = null;
                              } else {
                                state.selectedTemplateId = t.template_id;
                                const resp = await fetch(`${apiBase}/templates/${t.template_id}`);
                                if (resp.ok) state.templatePreview = (await resp.json()).structure;
                              }
                            },
                          }, [
                            h("div", { style: "display:flex;align-items:center;gap:8px" }, [
                              h("span", { style: "font-weight:600;font-size:.88rem;flex:1" }, t.name),
                              h("span", { class: "badge" }, t.source_format),
                              h("span", { style: "font-size:.72rem;color:#9ca3af" }, t.created_at?.split("T")[0] || ""),
                              h("button", {
                                class: "btn-view",
                                title: "Export JSON",
                                onClick: (e: Event) => {
                                  e.stopPropagation();
                                  fetch(`${apiBase}/templates/${t.template_id}`)
                                    .then(r => r.json())
                                    .then(data => {
                                      const blob = new Blob([JSON.stringify(data.structure, null, 2)], { type: "application/json" });
                                      const url = URL.createObjectURL(blob);
                                      const a = document.createElement("a");
                                      a.href = url; a.download = `${t.name.replace(/\s+/g, '_')}.template.json`; a.click();
                                      URL.revokeObjectURL(url);
                                    });
                                },
                              }, "⬇"),
                              h("button", {
                                class: "btn-delete",
                                title: "Delete template",
                                onClick: (e: Event) => { e.stopPropagation(); deleteTemplate(t.template_id); },
                              }, "✕"),
                            ]),
                          ]),
                        ),
                      ),
                  // Structure preview for selected template
                  state.templatePreview
                    ? h("div", {
                        style: "margin-top:12px;padding:14px 16px;background:#f9fafb;border:1px solid #e5e7eb;border-radius:8px;max-height:320px;overflow:auto",
                      }, [
                        // View mode toggle
                        h("div", { style: "display:flex;gap:4px;margin-bottom:10px" }, [
                          ...["visual", "json", "yaml", "xml"].map(mode =>
                            h("button", {
                              class: `btn btn-sm ${(state as any).templateViewMode === mode || (!((state as any).templateViewMode) && mode === "visual") ? "btn-primary" : "btn-outline"}`,
                              style: "padding:3px 10px;font-size:.72rem",
                              onClick: () => { (state as any).templateViewMode = mode; },
                            }, mode.toUpperCase()),
                          ),
                        ]),
                        // Render based on mode
                        ((state as any).templateViewMode === "json")
                          ? h("pre", { style: "font-size:.75rem;font-family:'Courier New',monospace;white-space:pre-wrap;word-break:break-word;margin:0;color:#374151" },
                              JSON.stringify(state.templatePreview, null, 2))
                          : ((state as any).templateViewMode === "yaml")
                          ? h("pre", { style: "font-size:.75rem;font-family:'Courier New',monospace;white-space:pre-wrap;word-break:break-word;margin:0;color:#374151" },
                              (() => {
                                const toYaml = (obj: any, indent = 0): string => {
                                  const pad = "  ".repeat(indent);
                                  if (Array.isArray(obj)) return obj.map(item => `${pad}- ${typeof item === "object" ? "\n" + toYaml(item, indent + 1) : item}`).join("\n");
                                  if (typeof obj === "object" && obj !== null) return Object.entries(obj).map(([k, v]) => {
                                    if (typeof v === "object" && v !== null) return `${pad}${k}:\n${toYaml(v, indent + 1)}`;
                                    return `${pad}${k}: ${JSON.stringify(v)}`;
                                  }).join("\n");
                                  return `${pad}${obj}`;
                                };
                                return toYaml(state.templatePreview);
                              })())
                          : ((state as any).templateViewMode === "xml")
                          ? h("pre", { style: "font-size:.75rem;font-family:'Courier New',monospace;white-space:pre-wrap;word-break:break-word;margin:0;color:#374151" },
                              (() => {
                                const esc = (s: string) => String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
                                const p = state.templatePreview;
                                let xml = `<template type="${esc(p.type||"")}" title="${esc(p.title||"")}" source_format="${esc(p.source_format||"")}">\n`;
                                if (p.fonts) xml += `  <fonts heading_font="${esc(p.fonts.heading_font||"")}" body_font="${esc(p.fonts.body_font||"")}" default_size_pt="${p.fonts.default_size_pt||""}"/>\n`;
                                if (p.page_layout) xml += `  <page_layout size="${esc(p.page_layout.size||"")}" orientation="${esc(p.page_layout.orientation||"")}">\n    <margins top="${p.page_layout.margins?.top||""}" bottom="${p.page_layout.margins?.bottom||""}" left="${p.page_layout.margins?.left||""}" right="${p.page_layout.margins?.right||""}"/>\n  </page_layout>\n`;
                                xml += "  <sections>\n";
                                for (const s of (p.sections||[])) {
                                  xml += `    <section${s.heading?` heading="${esc(s.heading)}"`:""}${s.style?` style="${esc(s.style)}"`:""}>\n`;
                                  for (const e of (s.elements||[])) {
                                    const attrs = Object.entries(e).filter(([k])=>k!=="type").map(([k,v])=>`${k}="${esc(Array.isArray(v)?v.join(" | "):String(v))}"`).join(" ");
                                    xml += `      <${e.type} ${attrs}/>\n`;
                                  }
                                  xml += "    </section>\n";
                                }
                                xml += "  </sections>\n</template>";
                                return xml;
                              })())
                          : [
                        // Visual mode (default)
                        h("div", { style: "display:flex;align-items:center;gap:8px;margin-bottom:10px;padding-bottom:8px;border-bottom:1px solid #e5e7eb" }, [
                          h("span", { class: "badge" }, state.templatePreview.type || "document"),
                          h("span", { style: "font-weight:600;font-size:.9rem" }, state.templates.find((t: any) => t.template_id === state.selectedTemplateId)?.name || "Template"),
                          state.templatePreview.title && state.templatePreview.title !== "Untitled"
                            ? h("span", { style: "color:#6b7280;font-size:.78rem;font-style:italic" }, `"${state.templatePreview.title}"`)
                            : null,
                          state.templatePreview.page_count ? h("span", { style: "color:#9ca3af;font-size:.75rem;margin-left:auto" }, `${state.templatePreview.page_count} pages`) : null,
                          state.templatePreview.table_count ? h("span", { style: "color:#9ca3af;font-size:.75rem" }, `${state.templatePreview.table_count} tables`) : null,
                        ]),
                        // Font and layout info
                        state.templatePreview.fonts || state.templatePreview.page_layout
                          ? h("div", { style: "display:flex;flex-wrap:wrap;gap:6px;margin-bottom:10px;padding-bottom:8px;border-bottom:1px solid #f3f4f6;font-size:.72rem;color:#6b7280" }, [
                              state.templatePreview.fonts?.heading_font ? h("span", {}, `Headings: ${state.templatePreview.fonts.heading_font}`) : null,
                              state.templatePreview.fonts?.body_font ? h("span", {}, `Body: ${state.templatePreview.fonts.body_font}`) : null,
                              state.templatePreview.fonts?.default_size_pt ? h("span", {}, `${state.templatePreview.fonts.default_size_pt}pt`) : null,
                              state.templatePreview.page_layout?.size && state.templatePreview.page_layout.size !== "unknown" ? h("span", {}, `Page: ${state.templatePreview.page_layout.size}`) : null,
                              state.templatePreview.page_layout?.orientation && state.templatePreview.page_layout.orientation !== "unknown" ? h("span", {}, state.templatePreview.page_layout.orientation) : null,
                            ])
                          : null,
                        ...(state.templatePreview.sections || []).map((s: any) =>
                          h("div", { style: "margin-bottom:8px" }, [
                            s.heading ? h("div", { style: `font-weight:600;font-size:.8rem;color:#374151;margin-bottom:3px;padding-left:${((s.level || 1) - 1) * 12}px` }, s.heading) : null,
                            s.row_count ? h("span", { style: "font-size:.72rem;color:#9ca3af;margin-left:4px" }, ` (${s.row_count}×${s.col_count})`) : null,
                            ...(s.elements || []).map((e: any) => {
                              if (e.type === "field") return h("div", { style: "padding:2px 0 2px 12px;color:#6366f1;font-size:.78rem" }, `📝 ${e.label || "Field"}: ___________`);
                              if (e.type === "checkbox") return h("div", { style: "padding:2px 0 2px 12px;font-size:.78rem" }, `☐ ${e.label}`);
                              if (e.type === "bullet") return h("div", { style: "padding:1px 0 1px 16px;font-size:.78rem;color:#4b5563" }, `• ${e.text}`);
                              if (e.type === "signature_line") return h("div", { style: "padding:2px 0 2px 12px;color:#9ca3af;font-size:.78rem" }, "✍️ Signature line");
                              if (e.type === "table_header") return h("div", { style: "padding:2px 0 2px 12px;font-size:.75rem;color:#6366f1;font-family:monospace" }, `┃ ${(e.columns || []).join(" │ ")}`);
                              if (e.type === "table_row") return h("div", { style: "padding:1px 0 1px 12px;font-size:.75rem;color:#6b7280;font-family:monospace" }, `│ ${(e.cells || []).join(" │ ")}`);
                              if (e.type === "index_row") return h("div", { style: "display:grid;grid-template-columns:repeat(3,1fr);gap:8px;padding:1px 0 1px 12px;font-size:.75rem;font-family:monospace" },
                                (e.columns || []).map((col: any) => {
                                  if (!col) return h("span", {});
                                  if (col.letter) return h("span", { style: "font-weight:700;color:#6366f1" }, col.letter);
                                  if (col.entry) return h("span", { style: "color:#374151" }, col.entry);
                                  return h("span", {}, String(col));
                                }),
                              );
                              if (e.type === "note") return h("div", { style: "padding:1px 0 1px 12px;font-size:.72rem;color:#9ca3af;font-style:italic" }, e.text);
                              if (e.type === "paragraph") return h("div", { style: "padding:1px 0 1px 12px;font-size:.78rem;color:#4b5563" }, e.text);
                              return null;
                            }),
                          ]),
                        ),
                        ],
                      ])
                    : null,
                ])
              : null,

            // Diagnostic panel
            state.mode === "diagnostic"
              ? h("div", { class: "create-panel" }, [
                  h("div", { style: "display:flex;align-items:center;justify-content:space-between;margin-bottom:12px" }, [
                    h("h2", { style: "font-size:.85rem;text-transform:uppercase;letter-spacing:.06em;color:#9ca3af;margin:0" }, "Template Fill Diagnostic"),
                  ]),
                  // Template selector + prompt
                  h("div", { style: "display:flex;gap:8px;margin-bottom:12px" }, [
                    h("select", {
                      class: "config-input",
                      style: "width:200px",
                      value: state.selectedTemplateId,
                      onChange: (e: Event) => { state.selectedTemplateId = (e.target as HTMLSelectElement).value; },
                    }, [
                      h("option", { value: "" }, "— Select template —"),
                      ...state.templates.map((t: any) => h("option", { value: t.template_id }, t.name)),
                    ]),
                    h("input", {
                      class: "search-input",
                      style: "flex:1",
                      placeholder: "Fill prompt (e.g. 'Write about HOA governance for Centerpointe Community')",
                      value: (state as any).diagPrompt || "",
                      onInput: (e: Event) => { (state as any).diagPrompt = (e.target as HTMLInputElement).value; },
                    }),
                    h("button", {
                      class: "btn btn-primary btn-sm",
                      disabled: !state.selectedTemplateId || !(state as any).diagPrompt || (state as any).diagLoading,
                      onClick: async () => {
                        (state as any).diagLoading = true;
                        (state as any).diagError = "";
                        try {
                          // 1. Get original template structure
                          const structResp = await fetch(`${apiBase}/templates/${state.selectedTemplateId}`);
                          const tmplData = await structResp.json();
                          (state as any).diagOriginal = tmplData.structure;

                          // 2. Get fill schema (analyze)
                          const schemaResp = await fetch(`${apiBase}/templates/${state.selectedTemplateId}/analyze`, { method: "POST" });
                          if (schemaResp.ok) {
                            (state as any).diagSchema = await schemaResp.json();
                          } else {
                            (state as any).diagSchema = { note: "Analyze endpoint not available — using stored structure" };
                          }

                          // 3. Fill and get result
                          const fillResp = await fetch(`${apiBase}/templates/${state.selectedTemplateId}/fill`, {
                            method: "POST",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify({ prompt: (state as any).diagPrompt }),
                          });
                          if (fillResp.ok) {
                            const blob = await fillResp.blob();
                            (state as any).diagFilledUrl = URL.createObjectURL(blob);
                            (state as any).diagFilledSize = (blob.size / 1024).toFixed(1);
                            (state as any).diagFilled = true;
                          } else {
                            const err = await fillResp.json();
                            (state as any).diagError = err.detail || "Fill failed";
                          }
                        } catch (e: any) {
                          (state as any).diagError = e.message;
                        } finally {
                          (state as any).diagLoading = false;
                        }
                      },
                    }, (state as any).diagLoading ? "Running..." : "▶ Run Diagnostic"),
                  ]),
                  (state as any).diagError
                    ? h("div", { class: "status status-error", style: "margin-bottom:8px" }, (state as any).diagError)
                    : null,
                  // Three-panel view
                  h("div", { style: "display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin-top:8px" }, [
                    // Panel 1: Original Template
                    h("div", { style: "border:1px solid #e5e7eb;border-radius:8px;overflow:hidden" }, [
                      h("div", { style: "background:#f8fafc;padding:8px 12px;border-bottom:1px solid #e5e7eb;font-size:.75rem;font-weight:600;color:#6366f1" }, "① Original Template"),
                      h("div", { style: "padding:10px;max-height:400px;overflow-y:auto;font-size:.72rem;font-family:'Courier New',monospace;line-height:1.6" },
                        (state as any).diagOriginal
                          ? [
                              h("div", { style: "margin-bottom:6px;color:#9ca3af" }, `Type: ${(state as any).diagOriginal.type || "?"} | Format: ${(state as any).diagOriginal.source_format || "?"}`),
                              h("div", { style: "margin-bottom:6px;color:#9ca3af" }, `Fonts: ${JSON.stringify((state as any).diagOriginal.fonts || {})}`),
                              h("div", { style: "margin-bottom:6px;color:#9ca3af" }, `Layout: ${JSON.stringify((state as any).diagOriginal.page_layout || {})}`),
                              ...((state as any).diagOriginal.sections || []).map((s: any) =>
                                h("div", { style: "margin-bottom:4px" }, [
                                  s.heading ? h("div", { style: "font-weight:600;color:#374151" }, s.heading) : null,
                                  ...(s.elements || []).slice(0, 3).map((e: any) =>
                                    h("div", { style: "color:#6b7280;padding-left:8px" }, `${e.type}: ${(e.text || e.label || "").substring(0, 50)}`),
                                  ),
                                  (s.elements || []).length > 3 ? h("div", { style: "color:#9ca3af;padding-left:8px" }, `+${s.elements.length - 3} more`) : null,
                                ]),
                              ),
                            ]
                          : [h("div", { style: "color:#9ca3af;text-align:center;padding:20px" }, "Run diagnostic to see template structure")],
                      ),
                    ]),
                    // Panel 2: Fill Schema (Intermediate)
                    h("div", { style: "border:1px solid #e5e7eb;border-radius:8px;overflow:hidden" }, [
                      h("div", { style: "background:#f8fafc;padding:8px 12px;border-bottom:1px solid #e5e7eb;font-size:.75rem;font-weight:600;color:#f59e0b" }, "② Fill Schema (Intermediate)"),
                      h("div", { style: "padding:10px;max-height:400px;overflow-y:auto;font-size:.72rem;font-family:'Courier New',monospace;line-height:1.6" },
                        (state as any).diagSchema
                          ? [h("pre", { style: "margin:0;white-space:pre-wrap;word-break:break-word;color:#374151" }, JSON.stringify((state as any).diagSchema, null, 2).substring(0, 3000))]
                          : [h("div", { style: "color:#9ca3af;text-align:center;padding:20px" }, "Run diagnostic to see fill schema")],
                      ),
                    ]),
                    // Panel 3: Filled Result
                    h("div", { style: "border:1px solid #e5e7eb;border-radius:8px;overflow:hidden" }, [
                      h("div", { style: "background:#f8fafc;padding:8px 12px;border-bottom:1px solid #e5e7eb;font-size:.75rem;font-weight:600;color:#16a34a" }, "③ Filled Result"),
                      h("div", { style: "padding:10px;max-height:400px;overflow-y:auto;font-size:.72rem;line-height:1.6" },
                        (state as any).diagFilled
                          ? [
                              h("div", { style: "text-align:center;padding:12px" }, [
                                h("div", { style: "font-size:2rem;margin-bottom:8px" }, "📄"),
                                h("div", { style: "font-weight:600;color:#374151;margin-bottom:4px" }, `Filled document (${(state as any).diagFilledSize} KB)`),
                                h("a", {
                                  href: (state as any).diagFilledUrl,
                                  download: "diagnostic_filled.docx",
                                  class: "btn btn-sm btn-primary",
                                  style: "display:inline-block;margin-top:8px;text-decoration:none",
                                }, "⬇ Download .docx"),
                              ]),
                            ]
                          : (state as any).diagError
                            ? [h("div", { style: "color:#dc2626;text-align:center;padding:20px" }, (state as any).diagError)]
                            : [h("div", { style: "color:#9ca3af;text-align:center;padding:20px" }, "Run diagnostic to generate filled document")],
                      ),
                    ]),
                  ]),
                ])
              : null,

            // Gap-to-Email panel
            state.mode === "gap-email"
              ? h("div", { class: "create-panel" }, [
                  h("h2", { style: "font-size:.85rem;text-transform:uppercase;letter-spacing:.06em;color:#9ca3af;margin:0 0 12px 0" }, "Gap-to-Email Pipeline"),
                  h("p", { style: "color:#9ca3af;font-size:.8rem;margin-bottom:16px" }, "Select a form, add vendors with their documents, and generate follow-up emails for missing items."),

                  // Form document autocomplete
                  h("div", { style: "margin-bottom:12px;position:relative" }, [
                    h("label", { style: "font-size:.75rem;color:#9ca3af;display:block;margin-bottom:4px" }, "Form/Application Document"),
                    h("input", {
                      style: "width:100%;padding:6px 8px;border:1px solid #374151;border-radius:6px;background:#1f2937;color:#f3f4f6;font-size:.8rem",
                      placeholder: "Start typing to search documents...",
                      value: state.gapFormSearch ?? "",
                      onInput: (e: Event) => {
                        (state as any).gapFormSearch = (e.target as HTMLInputElement).value;
                        (state as any).gapFormDropdownOpen = true;
                      },
                      onFocus: () => { (state as any).gapFormDropdownOpen = true; },
                    }),
                    state.gapFormDocId ? h("div", { style: "font-size:.7rem;color:#34d399;margin-top:3px" }, `✓ ${state.documents.find((d: any) => d.document_id === state.gapFormDocId)?.title || state.gapFormDocId}`) : null,
                    (state as any).gapFormDropdownOpen && (state as any).gapFormSearch
                      ? h("div", { style: "position:absolute;z-index:50;top:100%;left:0;right:0;max-height:200px;overflow-y:auto;background:#1f2937;border:1px solid #374151;border-radius:6px;margin-top:2px;box-shadow:0 4px 12px rgba(0,0,0,.4)" },
                          state.documents
                            .filter((d: any) => (d.title || d.original_filename || "").toLowerCase().includes(((state as any).gapFormSearch || "").toLowerCase()))
                            .slice(0, 10)
                            .map((d: any) =>
                              h("div", {
                                style: "padding:6px 10px;font-size:.75rem;color:#d1d5db;cursor:pointer;border-bottom:1px solid #374151",
                                onMousedown: (e: Event) => {
                                  e.preventDefault();
                                  state.gapFormDocId = d.document_id;
                                  (state as any).gapFormSearch = d.title || d.original_filename;
                                  (state as any).gapFormDropdownOpen = false;
                                },
                              }, d.title || d.original_filename)
                            )
                        )
                      : null,
                  ]),

                  // Context documents auto-discovered - no manual selection needed

                  // Vendors list
                  h("div", { style: "margin-bottom:12px;border:1px solid #374151;border-radius:8px;padding:12px" }, [
                    h("label", { style: "font-size:.75rem;color:#9ca3af;display:block;margin-bottom:8px" }, `Vendors (${state.gapVendors.length})`),
                    ...state.gapVendors.map((v: any, idx: number) =>
                      h("div", { style: "display:flex;align-items:center;gap:8px;margin-bottom:6px;padding:6px;background:#1f2937;border-radius:4px;font-size:.8rem" }, [
                        h("span", { style: "flex:1;color:#f3f4f6" }, `${v.name} (${v.doc_ids.length} docs)`),
                        h("button", {
                          class: "btn btn-sm",
                          style: "color:#ef4444;border:none;padding:2px 6px",
                          onClick: () => { state.gapVendors.splice(idx, 1); },
                        }, "×"),
                      ])
                    ),

                    // Add vendor form
                    h("div", { style: "margin-top:8px;padding-top:8px;border-top:1px solid #374151" }, [
                      h("div", { style: "margin-bottom:6px" }, [
                        h("input", {
                          style: "width:100%;padding:6px 8px;border:1px solid #374151;border-radius:4px;background:#111827;color:#f3f4f6;font-size:.8rem",
                          placeholder: "Type vendor name (e.g., Brax Roofing)...",
                          value: state.gapNewVendorName,
                          onInput: async (e: Event) => {
                            const val = (e.target as HTMLInputElement).value;
                            state.gapNewVendorName = val;
                            if (val.length >= 2) {
                              // Auto-find docs matching vendor name (searches title + content)
                              try {
                                const res = await fetch(`${apiBase}/search`, {
                                  method: "POST",
                                  headers: { "Content-Type": "application/json" },
                                  body: JSON.stringify({ query: val, mode: "hybrid", page: 1, page_size: 20 }),
                                });
                                const data = await res.json();
                                const results = data.results || [];
                                // Dedupe by document_id, keep all results from search
                                const seen = new Set<string>();
                                const matchedDocs: string[] = [];
                                let foundContact = "";
                                for (const r of results) {
                                  if (!seen.has(r.document_id)) {
                                    seen.add(r.document_id);
                                    matchedDocs.push(r.document_id);
                                    // Try to extract contact from snippet
                                    if (!foundContact) {
                                      const emailMatch = (r.snippet || "").match(/[\w.+-]+@[\w-]+\.[\w.]+/);
                                      if (emailMatch) foundContact = emailMatch[0];
                                    }
                                  }
                                }
                                state.gapNewVendorDocs = matchedDocs;
                                if (foundContact && !state.gapNewVendorContact) state.gapNewVendorContact = foundContact;
                              } catch { /* ignore search errors */ }
                            } else {
                              state.gapNewVendorDocs = [];
                            }
                          },
                        }),
                      ]),
                      // Contact (auto-populated or manual)
                      h("input", {
                        style: "width:100%;padding:4px 8px;border:1px solid #374151;border-radius:4px;background:#111827;color:#f3f4f6;font-size:.75rem;margin-bottom:6px",
                        placeholder: "Contact (auto-populated or type manually)",
                        value: state.gapNewVendorContact,
                        onInput: (e: Event) => { state.gapNewVendorContact = (e.target as HTMLInputElement).value; },
                      }),
                      // Auto-populated docs list (editable)
                      state.gapNewVendorDocs.length
                        ? h("div", { style: "border:1px solid #374151;border-radius:4px;padding:4px 6px;margin-bottom:6px;background:#111827" }, [
                            h("div", { style: "font-size:.7rem;color:#6b7280;margin-bottom:3px" }, `Documents found (${state.gapNewVendorDocs.length}):`),
                            ...state.gapNewVendorDocs.map((id: string) => {
                              const doc = state.documents.find((d: any) => d.document_id === id);
                              return h("div", { style: "display:flex;align-items:center;gap:4px;padding:2px 0;font-size:.7rem;color:#d1d5db" }, [
                                h("span", { style: "flex:1" }, doc ? (doc.title || doc.original_filename) : id),
                                h("button", {
                                  style: "color:#ef4444;border:none;background:none;cursor:pointer;font-size:.75rem;padding:0 3px",
                                  onClick: () => { state.gapNewVendorDocs = state.gapNewVendorDocs.filter((i: string) => i !== id); },
                                }, "×"),
                              ]);
                            }),
                          ])
                        : state.gapNewVendorName.length >= 2
                          ? h("div", { style: "font-size:.7rem;color:#6b7280;margin-bottom:6px" }, "No matching documents found")
                          : null,
                      // Add more docs manually
                      h("div", { style: "position:relative;margin-bottom:6px" }, [
                        h("input", {
                          style: "width:100%;padding:4px 8px;border:1px solid #374151;border-radius:4px;background:#111827;color:#f3f4f6;font-size:.7rem",
                          placeholder: "+ Add more documents...",
                          value: (state as any).gapNewVendorDocSearch || "",
                          onInput: (e: Event) => { (state as any).gapNewVendorDocSearch = (e.target as HTMLInputElement).value; (state as any).gapNewVendorDocDropdown = true; },
                          onFocus: () => { (state as any).gapNewVendorDocDropdown = true; },
                        }),
                        (state as any).gapNewVendorDocDropdown && (state as any).gapNewVendorDocSearch
                          ? h("div", { style: "position:absolute;z-index:50;top:100%;left:0;right:0;max-height:150px;overflow-y:auto;background:#1f2937;border:1px solid #374151;border-radius:4px;margin-top:2px;box-shadow:0 4px 12px rgba(0,0,0,.4)" },
                              state.documents
                                .filter((d: any) => !state.gapNewVendorDocs.includes(d.document_id) && (d.title || d.original_filename || "").toLowerCase().includes(((state as any).gapNewVendorDocSearch || "").toLowerCase()))
                                .slice(0, 8)
                                .map((d: any) =>
                                  h("div", {
                                    style: "padding:5px 8px;font-size:.7rem;color:#d1d5db;cursor:pointer;border-bottom:1px solid #374151",
                                    onMousedown: (e: Event) => {
                                      e.preventDefault();
                                      state.gapNewVendorDocs.push(d.document_id);
                                      (state as any).gapNewVendorDocSearch = "";
                                      (state as any).gapNewVendorDocDropdown = false;
                                    },
                                  }, d.title || d.original_filename)
                                )
                            )
                          : null,
                      ]),
                      h("input", {
                        style: "width:100%;padding:4px 8px;border:1px solid #374151;border-radius:4px;background:#111827;color:#f3f4f6;font-size:.75rem;margin-bottom:6px",
                        placeholder: "Notes (optional - e.g., 'offered to help with HOA docs')",
                        value: state.gapNewVendorNotes,
                        onInput: (e: Event) => { state.gapNewVendorNotes = (e.target as HTMLInputElement).value; },
                      }),
                      h("button", {
                        class: "btn btn-sm btn-outline",
                        style: state.gapNewVendorName && state.gapNewVendorDocs.length ? "" : "opacity:0.5",
                        disabled: !state.gapNewVendorName || !state.gapNewVendorDocs.length,
                        onClick: () => {
                          if (state.gapNewVendorName && state.gapNewVendorDocs.length) {
                            state.gapVendors.push({
                              name: state.gapNewVendorName,
                              contact: state.gapNewVendorContact,
                              doc_ids: [...state.gapNewVendorDocs],
                              notes: state.gapNewVendorNotes,
                            });
                            state.gapNewVendorName = "";
                            state.gapNewVendorContact = "";
                            state.gapNewVendorDocs = [];
                            state.gapNewVendorNotes = "";
                            (state as any).gapNewVendorDocSearch = "";
                          }
                        },
                      }, "+ Add Vendor"),
                    ]),
                  ]),

                  // Example email (optional)
                  h("details", { style: "margin-bottom:12px" }, [
                    h("summary", { style: "font-size:.75rem;color:#9ca3af;cursor:pointer" }, "Example Email (optional - for tone matching)"),
                    h("textarea", {
                      style: "width:100%;height:120px;padding:8px;border:1px solid #374151;border-radius:6px;background:#1f2937;color:#f3f4f6;font-size:.75rem;margin-top:6px;font-family:monospace",
                      placeholder: "Paste an example email here to match its tone and structure...",
                      value: state.gapExampleEmail,
                      onInput: (e: Event) => { state.gapExampleEmail = (e.target as HTMLTextAreaElement).value; },
                    }),
                  ]),

                  // Generate button
                  h("button", {
                    class: "btn btn-primary",
                    style: "width:100%;margin-bottom:16px",
                    disabled: !state.gapFormDocId || state.gapVendors.length === 0 || state.gapLoading,
                    onClick: async () => {
                      state.gapLoading = true;
                      state.gapError = "";
                      state.gapResults = [];
                      try {
                        const res = await fetch(`${apiBase}/gap-to-email`, {
                          method: "POST",
                          headers: { "Content-Type": "application/json" },
                          body: JSON.stringify({
                            form_document_id: state.gapFormDocId,
                            vendor_groups: state.gapVendors,
                            context_document_ids: [],
                            example_email: state.gapExampleEmail,
                          }),
                        });
                        if (!res.ok) throw new Error(await res.text());
                        const data = await res.json();
                        state.gapResults = data.results || [];
                      } catch (e: any) {
                        state.gapError = e.message || "Failed to generate emails";
                      } finally {
                        state.gapLoading = false;
                      }
                    },
                  }, state.gapLoading ? "Analyzing & Generating..." : "🔍 Analyze Gaps & Generate Emails"),

                  // Error
                  state.gapError ? h("div", { style: "color:#ef4444;font-size:.8rem;margin-bottom:12px" }, state.gapError) : null,

                  // Results
                  ...state.gapResults.map((r: any) =>
                    h("div", { style: "margin-bottom:16px;border:1px solid #374151;border-radius:8px;padding:12px" }, [
                      h("div", { style: "display:flex;justify-content:space-between;align-items:center;margin-bottom:8px" }, [
                        h("h3", { style: "margin:0;font-size:.9rem;color:#f3f4f6" }, r.vendor_name),
                        h("span", { style: "font-size:.7rem;color:#9ca3af" }, r.contact),
                      ]),
                      r.gaps.length ? h("div", { style: "margin-bottom:8px" }, [
                        h("div", { style: "font-size:.7rem;color:#f59e0b;margin-bottom:4px" }, "Gaps Found:"),
                        ...r.gaps.map((g: string) => h("div", { style: "font-size:.75rem;color:#fbbf24;padding-left:8px" }, `• ${g}`)),
                      ]) : null,
                      h("div", { style: "background:#111827;border-radius:6px;padding:10px;font-size:.75rem;color:#d1d5db;white-space:pre-wrap;font-family:monospace;max-height:400px;overflow-y:auto" }, r.email),
                      h("button", {
                        class: "btn btn-sm btn-outline",
                        style: "margin-top:8px",
                        onClick: () => { navigator.clipboard.writeText(r.email); },
                      }, "📋 Copy Email"),
                    ])
                  ),
                ])
              : null,

            // Health panel (k8s pod status)
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
                                      : name === "app"
                                        ? `${info.tag} · ${info.git_hash} · ${info.build_date}`
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

                  // Kubernetes Cluster section (collapsible)
                  h("div", { class: "collapsible" }, [
                    h("div", {
                      class: "collapsible-header",
                      onClick: () => { state.k8sOpen = !state.k8sOpen; if (state.k8sOpen && !state.k8sHealth) loadK8sHealth(); },
                    }, [
                      h("span", state.k8sOpen ? "▼" : "▶"),
                      h("span", " Kubernetes Cluster"),
                      state.k8sLoading ? h("span", { class: "spinner spinner-dark", style: "margin-left:8px" }) : null,
                    ]),
                    state.k8sOpen ? h("div", { class: "collapsible-body" }, [
                      state.k8sHealth && !state.k8sHealth.available
                        ? h("div", { class: "status status-muted" }, `Not available: ${state.k8sHealth.error || "cluster unreachable"}`)
                        : null,
                      state.k8sHealth && state.k8sHealth.available
                        ? h("div", [
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
                        : !state.k8sLoading ? h("div", { class: "status status-muted" }, "Loading...") : null,
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
                      ...Object.entries(state.configEdits)
                        .filter(([key]) => key !== "BEDROCK_GENERATE_MODEL_ID" && key !== "BEDROCK_TASK_MODEL_ID" && key !== "WORKER_CONCURRENCY" && key !== "MAX_WORKER_CONCURRENCY")
                        .map(([key, val]: [string, string]) => {
                        const isSecret = key.includes("SECRET") || key.includes("API_TOKEN");
                        const isReadOnly = key === "WORKER_CONCURRENCY" || key === "MAX_WORKER_CONCURRENCY" || key === "OPENSEARCH_HOST" || key === "OPENSEARCH_PORT";
                        const isModelSelect = key === "BEDROCK_MODEL_ID" || key === "BEDROCK_GENERATE_MODEL_ID" || key === "BEDROCK_TASK_MODEL_ID" || key === "BEDROCK_TASK_SINGLE_MODEL_ID" || key === "BEDROCK_TASK_MULTI_MODEL_ID" || key === "BEDROCK_DETECT_MODEL_ID" || key === "BEDROCK_TEMPLATE_MODEL_ID" || key === "BEDROCK_VISION_MODEL_ID" || key === "BEDROCK_EMBED_MODEL_ID";
                        const isRegionSelect = key === "AWS_REGION";
                        const models = key === "BEDROCK_VISION_MODEL_ID" ? state.visionModels : key === "BEDROCK_EMBED_MODEL_ID" ? state.embeddingModels : state.qaModels;
                        // For task model selectors, add context window hints to help user choose
                        const modelList = (key === "BEDROCK_TASK_SINGLE_MODEL_ID" || key === "BEDROCK_TASK_MULTI_MODEL_ID")
                          ? models.map((m: any) => {
                              const id = m.id.toLowerCase();
                              let ctx = "";
                              if (id.includes("nova-pro") || id.includes("nova-lite") || id.includes("nova-2")) ctx = " [300k ctx]";
                              else if (id.includes("claude")) ctx = " [200k ctx]";
                              else if (id.includes("llama") || id.includes("mistral") || id.includes("deepseek") || id.includes("qwen")) ctx = " [128k ctx]";
                              else ctx = " [~32-128k ctx]";
                              const hint = key === "BEDROCK_TASK_SINGLE_MODEL_ID"
                                ? (ctx.includes("300k") || ctx.includes("200k") ? " ★" : "")
                                : (id.includes("mistral.magistral") || id.includes("llama") || id.includes("deepseek") ? " ★" : "");
                              return { ...m, label: m.label + ctx + hint };
                            })
                          : key === "BEDROCK_MODEL_ID"
                            // Ask AI: mark fast/cheap models
                            ? models.map((m: any) => {
                                const id = m.id.toLowerCase();
                                const hint = (id.includes("haiku") || id.includes("nova-lite") || id.includes("nova-pro") || id.includes("nova-micro")) ? " ★ fast" : "";
                                return { ...m, label: m.label + hint };
                              })
                          : key === "BEDROCK_DETECT_MODEL_ID"
                            // Format detection: only needs tiny fast model
                            ? models.map((m: any) => {
                                const id = m.id.toLowerCase();
                                const hint = (id.includes("micro") || id.includes("nova-lite") || id.includes("haiku") || id.includes("mistral-large")) ? " ★ recommended" : "";
                                return { ...m, label: m.label + hint };
                              })
                          : models;

                        return h("div", { class: "config-row" }, [
                          h("label", { class: "config-label" }, ({
                            "BEDROCK_MODEL_ID": "Ask AI Model (fast, for interactive Q&A)",
                            "BEDROCK_TASK_SINGLE_MODEL_ID": "Task Model — Single Pass (large context window)",
                            "BEDROCK_TASK_MULTI_MODEL_ID": "Task Model — Structured Pipeline (complex tasks)",
                            "BEDROCK_DETECT_MODEL_ID": "Format Detection Model (fast/cheap, returns 1 word)",
                            "BEDROCK_TEMPLATE_MODEL_ID": "Template Extraction Model (needs strong JSON)",
                            "BEDROCK_VISION_MODEL_ID": "Vision OCR Model (must support images)",
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
                                }, modelList.map((m: any) => h("option", { value: m.id, selected: m.id === val }, m.label)))
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
                      // Pricing gap warning
                      state.usageData.by_model.some((m: any) => m.calls > 0 && Number(m.cost) === 0)
                        ? h("div", { style: "background:#fffbeb;border:1px solid #f59e0b;border-radius:6px;padding:8px 12px;margin-bottom:10px;font-size:.75rem;color:#92400e" }, [
                            h("strong", "⚠️ Pricing unavailable for some models: "),
                            h("span", state.usageData.by_model.filter((m: any) => m.calls > 0 && Number(m.cost) === 0).map((m: any) => m.model_id.replace("us.","")).join(", ")),
                            h("br"),
                            h("span", { style: "color:#a16207" }, "Token counts are accurate. Cost estimates will appear once AWS publishes pricing for these models. Developer: check periodically with 'aws bedrock' pricing updates."),
                          ])
                        : null,
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
                                    h("span", { class: "usage-model-summary" }, Number(m.cost) === 0 && m.calls > 0 ? "⚠️ no pricing" : `$${Number(m.cost).toFixed(4)}`),
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
            state.mode !== "settings" && state.mode !== "create" && state.mode !== "tasks" && state.mode !== "templates" && state.mode !== "diagnostic" && state.mode !== "gap-email" ? h("div", { class: "search-row" }, [
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
          state.mode !== "settings" && state.mode !== "create" && (hasResults.value || state.searchError || state.searchTime !== null)
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
                ...(state.mode === "ask" ? state.citations : state.results).map((r: any, idx: number) => {
                  const citKey = `cite_${idx}`;
                  const isOpen = (state as any)[citKey];
                  return h("div", { class: "result-item" }, [
                    h("div", { class: "result-header", style: "display:flex;align-items:center;gap:8px;cursor:pointer", onClick: () => ((state as any)[citKey] = !isOpen) }, [
                      h("span", { style: "font-size:.7rem;color:#9ca3af" }, isOpen ? "▼" : "▶"),
                      h("a", {
                        class: "result-title",
                        href: `${apiBase}/documents/${r.document_id}/file`,
                        target: "_blank",
                        title: "Open document",
                        onClick: (e: Event) => e.stopPropagation(),
                      }, r.title),
                      h("span", { class: "result-meta" }, [
                        r.document_type ? h("span", { class: "badge" }, r.document_type) : null,
                        r.score != null ? h("span", { style: "font-size:.7rem;color:#9ca3af;margin-left:4px" }, `score ${r.score}`) : null,
                      ]),
                    ]),
                    isOpen ? h("div", { class: "result-snippet", innerHTML: (r.snippet || "").replace(/</g, "&lt;").replace(/&lt;em&gt;/g, "<mark>").replace(/&lt;\/em&gt;/g, "</mark>") }) : null,
                  ]);
                }),
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
                      state.uploadStatus = "Upload cancelled — queue flushed";
                      state.uploadLog = state.uploadLog.filter((l: any) => l.status === "done");
                      localStorage.removeItem("upload_batch_id");
                      localStorage.removeItem("upload_total");
                      await loadDocuments();
                    },
                  }, "✕ Cancel & Flush Queue")
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
                                    title: d.original_filename || d.title,
                                  }, d.title),
                                  h("span", { style: "display:flex;gap:6px;align-items:center" }, [
                                    h("span", { class: "badge badge-date", title: "Document date" }, d.document_date || "—"),
                                    h("span", { class: "badge badge-upload", title: "Uploaded" }, d.uploaded_at ? d.uploaded_at.split("T")[0] : "—"),
                                    h("span", { class: "badge" }, d.document_type),
                                    h("span", {
                                      class: `badge ${d.status === "indexed" ? "badge-green" : ""}`,
                                    }, d.status),
                                    h("button", {
                                      class: "btn-view",
                                      title: "Preview document",
                                      onClick: () => previewDoc(d),
                                    }, "📄"),
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
        // Preview modal
        (state as any).previewDoc
          ? h("div", { class: "preview-overlay", onClick: (e: Event) => { if (e.target === e.currentTarget) (state as any).previewDoc = null; } }, [
              h("div", { class: "preview-modal" }, [
                h("div", { class: "preview-header" }, [
                  h("span", { class: "preview-title" }, (state as any).previewDoc.title),
                  h("button", { class: "preview-close", onClick: () => (state as any).previewDoc = null }, "✕"),
                ]),
                h("div", {
                  class: (state as any).previewExt === "docx" || (state as any).previewExt === "doc" ? "preview-body preview-docx" : "preview-body",
                  ref: (el: any) => {
                    if (!el) return;
                    const ext = (state as any).previewExt;
                    const docId = (state as any).previewDoc?.document_id;
                    if (!docId) return;
                    if (ext === "docx" || ext === "doc") {
                      if (el.dataset.loaded === docId) return;
                      el.dataset.loaded = docId;
                      el.innerHTML = "<p style='color:#9ca3af;font-size:.85rem'>Loading preview...</p>";
                      fetch(`${apiBase}/documents/${docId}/file`)
                        .then(r => r.blob())
                        .then(blob => { el.innerHTML = ""; return renderAsync(blob, el); })
                        .catch(() => { el.innerHTML = "<p style='color:#dc2626'>Failed to load preview</p>"; });
                    } else if (ext === "png" || ext === "jpg" || ext === "jpeg" || ext === "tiff" || ext === "tif") {
                      if (el.dataset.loaded === docId) return;
                      el.dataset.loaded = docId;
                      el.innerHTML = "";
                      const img = document.createElement("img");
                      img.src = `${apiBase}/documents/${docId}/preview`;
                      el.appendChild(img);
                    } else {
                      if (el.dataset.loaded === docId) return;
                      el.dataset.loaded = docId;
                      el.innerHTML = "";
                      const iframe = document.createElement("iframe");
                      iframe.src = `${apiBase}/documents/${docId}/preview`;
                      el.appendChild(iframe);
                    }
                  },
                }),
              ]),
            ])
          : null,
      ]);
  },
}).mount("#app");
