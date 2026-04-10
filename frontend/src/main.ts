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
  }>,

  // Search / Ask / Settings mode
  query: "",
  mode: "search" as "search" | "ask" | "settings",
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
  const supported = [".pdf", ".docx", ".txt", ".md"];
  const files = state.uploadFiles.filter(f =>
    supported.some(ext => f.name.toLowerCase().endsWith(ext))
  );
  if (files.length === 0) {
    state.uploadStatus = "No supported files found (PDF, DOCX, TXT, MD)";
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
            state.uploadLog[idx] = { file: msg.file, status: "done", detail: `${msg.category} / ${msg.document_type}` };
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

async function loadUsage() {
  try {
    const resp = await fetch(`${apiBase}/admin/usage`);
    state.usageData = await resp.json();
  } catch { /* ignore */ }
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
.log-entry{display:flex;gap:6px;align-items:center;padding:3px 4px;border-bottom:1px solid #f9fafb}
.log-entry:last-child{border-bottom:none}
.log-icon{flex-shrink:0;width:18px;text-align:center}
.log-file{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#374151}
.log-detail{flex-shrink:0;color:#9ca3af;font-size:.75rem;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
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
                class: `btn btn-sm btn-outline ${state.mode === "settings" ? "active" : ""}`,
                onClick: () => { state.mode = "settings"; loadHealthCheck(); loadConfig(); },
              }, "⚙ Settings"),
            ]),

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
                        const isModelSelect = key === "BEDROCK_MODEL_ID" || key === "BEDROCK_VISION_MODEL_ID";
                        const isRegionSelect = key === "AWS_REGION";
                        const models = key === "BEDROCK_VISION_MODEL_ID" ? state.visionModels : state.qaModels;

                        return h("div", { class: "config-row" }, [
                          h("label", { class: "config-label" }, ({
                            "BEDROCK_MODEL_ID": "Ask AI Model",
                            "BEDROCK_VISION_MODEL_ID": "Vision OCR Model",
                            "AWS_REGION": "AWS Region",
                            "BOOKSTACK_URL": "BookStack URL",
                            "BOOKSTACK_TOKEN_ID": "BookStack Token ID",
                            "BOOKSTACK_TOKEN_SECRET": "BookStack Secret",
                            "CONFLUENCE_URL": "Confluence URL",
                            "CONFLUENCE_EMAIL": "Confluence Email",
                            "CONFLUENCE_API_TOKEN": "Confluence Token",
                            "TRACK_USAGE": "Track Usage & Cost",
                            "OPENSEARCH_HOST": "OpenSearch Host",
                            "OPENSEARCH_PORT": "OpenSearch Port",
                          } as Record<string, string>)[key] || key),
                          isRegionSelect
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
            state.mode !== "settings" ? h("div", { class: "search-row" }, [
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
          state.mode !== "settings" && (hasResults.value || state.searchError || state.searchTime !== null)
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

          // Upload card (files or folder)
          h("div", { class: "card" }, [
            h("h2", "Upload Documents"),
            h("div", { class: "upload-row" }, [
              h("input", {
                type: "file",
                accept: ".pdf,.docx,.txt,.md",
                multiple: true,
                disabled: state.uploadLoading,
                onChange: (e: Event) => {
                  const files = (e.target as HTMLInputElement).files;
                  state.uploadFiles = files ? Array.from(files) : [];
                },
              }),
              h("span", { style: "color:#9ca3af;font-size:.8rem" }, "or"),
              h("input", {
                type: "file",
                webkitdirectory: true,
                disabled: state.uploadLoading,
                onChange: (e: Event) => {
                  const files = (e.target as HTMLInputElement).files;
                  state.uploadFiles = files ? Array.from(files) : [];
                },
              }),
              h("button", {
                class: "btn btn-primary btn-sm",
                disabled: state.uploadLoading || state.uploadFiles.length === 0,
                onClick: upload,
              }, [
                state.uploadLoading
                  ? "Processing..."
                  : `Upload${state.uploadFiles.length > 1 ? ` (${state.uploadFiles.length})` : ""}`,
                state.uploadLoading ? h("span", { class: "spinner" }) : null,
              ]),
            ]),
            // Live progress log
            state.uploadLog.length > 0
              ? h("div", { class: "upload-log" },
                  state.uploadLog.map((entry: any) =>
                    h("div", { class: `log-entry log-${entry.status}` }, [
                      h("span", { class: "log-icon" },
                        entry.status === "uploading" ? "⏳" : entry.status === "done" ? "✅" : "❌"),
                      h("span", { class: "log-file" }, entry.file),
                      h("span", { class: "log-detail" }, entry.detail),
                    ])
                  )
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
                                      class: "btn-delete",
                                      title: "Delete",
                                      onClick: () => deleteDoc(d.document_id),
                                    }, "✕"),
                                  ]),
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
