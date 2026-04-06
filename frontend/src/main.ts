import { createApp, h, reactive, computed } from "vue";

type SearchResult = {
  document_id: string;
  chunk_id: string;
  title: string;
  snippet: string;
  score: number;
  source_type: string;
  document_type: string;
};
type Citation = { document_id: string; chunk_id: string; title: string; snippet: string };

const apiBase = location.hostname === "app.localhost"
  ? `${location.protocol}//api.localhost`
  : location.hostname === "localhost" && location.port === "5173"
    ? "http://localhost:8000"
    : `${location.protocol}//${location.hostname}:8000`;

const state = reactive({
  uploadFile: null as File | null,
  query: "",
  mode: "search" as "search" | "ask",
  results: [] as SearchResult[],
  answer: "",
  citations: [] as Citation[],
  documents: [] as Array<{ document_id: string; title: string; document_type: string; status: string }>,
  uploadStatus: "",
  uploadLoading: false,
  searchLoading: false,
  searchError: "",
  searchTime: null as number | null,
});

const hasResults = computed(() => state.results.length > 0 || state.answer);

async function loadDocuments() {
  try {
    state.documents = await (await fetch(`${apiBase}/documents`)).json();
  } catch { /* backend may be down */ }
}

async function upload() {
  if (!state.uploadFile) { state.uploadStatus = "Choose a file first"; return; }
  state.uploadLoading = true;
  state.uploadStatus = `Uploading ${state.uploadFile.name}...`;
  try {
    const body = new FormData();
    body.append("file", state.uploadFile);
    const res = await fetch(`${apiBase}/ingest/upload`, { method: "POST", body });
    if (!res.ok) { state.uploadStatus = `Upload failed: ${await res.text()}`; return; }
    const data = await res.json();
    state.uploadStatus = `Uploaded and indexed: ${state.uploadFile.name}`;
    state.uploadFile = null;
    // Reset the file input
    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    if (fileInput) fileInput.value = "";
    await loadDocuments();
  } catch (e: any) {
    state.uploadStatus = `Upload error: ${e.message || "Could not reach server"}`;
  } finally {
    state.uploadLoading = false;
  }
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
.upload-row{display:flex;gap:8px;align-items:center}
.upload-row input[type=file]{font-size:.85rem}
.status{font-size:.8rem;margin-top:8px}
.status-info{color:#6366f1}
.status-success{color:#16a34a}
.status-error{color:#dc2626}
.status-muted{color:#9ca3af}
.answer-box{background:#f0fdf4;border-left:3px solid #22c55e;padding:12px 16px;border-radius:6px;margin-bottom:12px;font-size:.9rem;line-height:1.5}
.result-item{padding:12px 0;border-bottom:1px solid #f3f4f6}
.result-item:last-child{border-bottom:none}
.result-title{font-weight:600;font-size:.9rem;color:#1a1a2e}
.result-meta{font-size:.75rem;color:#9ca3af;margin-top:2px}
.result-snippet{font-size:.85rem;color:#4b5563;margin-top:6px;line-height:1.45}
.doc-list{list-style:none}
.doc-list li{padding:8px 0;border-bottom:1px solid #f3f4f6;font-size:.85rem;display:flex;justify-content:space-between;align-items:center}
.doc-list li:last-child{border-bottom:none}
.badge{display:inline-block;padding:2px 8px;border-radius:4px;font-size:.7rem;font-weight:600;background:#eef2ff;color:#6366f1}
.badge-green{background:#f0fdf4;color:#16a34a}
.empty{color:#9ca3af;font-size:.85rem;text-align:center;padding:20px 0}
.search-meta{display:flex;gap:12px;align-items:center;margin-bottom:8px;font-size:.78rem;color:#9ca3af}
.spinner{display:inline-block;width:16px;height:16px;border:2px solid rgba(255,255,255,.3);border-top-color:#fff;border-radius:50%;animation:spin .6s linear infinite;margin-left:8px;vertical-align:middle}
.spinner-dark{border:2px solid #e5e7eb;border-top-color:#6366f1}
@keyframes spin{to{transform:rotate(360deg)}}
`;

createApp({
  setup() {
    loadDocuments();
    return () =>
      h("div", [
        h("style", css),
        h("div", { class: "shell" }, [
          // Header
          h("div", { class: "header" }, [
            h("h1", "📄 House Document Search"),
            h("p", "Upload, search, and ask questions about your documents"),
          ]),

          // Search card
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
            ]),
            h("div", { class: "search-row" }, [
              h("input", {
                class: "search-input",
                value: state.query,
                disabled: state.searchLoading,
                placeholder: state.mode === "search" ? "Search documents..." : "Ask a question about your documents...",
                onInput: (e: Event) => (state.query = (e.target as HTMLInputElement).value),
                onKeydown: (e: KeyboardEvent) => { if (e.key === "Enter" && !state.searchLoading) submit(); },
              }),
              h("button", {
                class: "btn btn-primary",
                disabled: state.searchLoading,
                onClick: submit,
              }, [
                state.searchLoading ? "Searching..." : (state.mode === "search" ? "Search" : "Ask"),
                state.searchLoading ? h("span", { class: "spinner" }) : null,
              ]),
            ]),
          ]),

          // Results
          (hasResults.value || state.searchError || state.searchTime !== null)
            ? h("div", { class: "card" }, [
                h("h2", "Results"),
                // Search metadata
                state.searchTime !== null
                  ? h("div", { class: "search-meta" }, [
                      state.results.length > 0 ? `${state.results.length} result${state.results.length === 1 ? "" : "s"}` : null,
                      state.citations.length > 0 ? `${state.citations.length} citation${state.citations.length === 1 ? "" : "s"}` : null,
                      `${state.searchTime}ms`,
                    ].filter(Boolean).join(" · "))
                  : null,
                // Error
                state.searchError
                  ? h("div", { class: "status status-muted", style: "text-align:center;padding:12px 0;" }, state.searchError)
                  : null,
                // Answer
                state.answer
                  ? h("div", { class: "answer-box" }, state.answer)
                  : null,
                // Result items
                ...(state.mode === "ask" ? state.citations : state.results).map((r: any) =>
                  h("div", { class: "result-item" }, [
                    h("div", { class: "result-title" }, r.title),
                    h("div", { class: "result-meta" }, [
                      r.document_type ? h("span", { class: "badge" }, r.document_type) : null,
                      r.score != null ? ` · score ${r.score}` : null,
                    ]),
                    h("div", { class: "result-snippet" }, r.snippet),
                  ])
                ),
              ])
            : null,

          // Upload card
          h("div", { class: "card" }, [
            h("h2", "Upload Document"),
            h("div", { class: "upload-row" }, [
              h("input", {
                type: "file",
                accept: ".pdf,.docx,.txt,.md",
                disabled: state.uploadLoading,
                onChange: (e: Event) => {
                  state.uploadFile = (e.target as HTMLInputElement).files?.[0] || null;
                },
              }),
              h("button", {
                class: "btn btn-primary btn-sm",
                disabled: state.uploadLoading,
                onClick: upload,
              }, [
                state.uploadLoading ? "Uploading..." : "Upload",
                state.uploadLoading ? h("span", { class: "spinner" }) : null,
              ]),
            ]),
            state.uploadStatus
              ? h("div", {
                  class: `status ${state.uploadLoading ? "status-info" : (state.uploadStatus.startsWith("Upload") && !state.uploadStatus.includes("fail") && !state.uploadStatus.includes("error") ? "status-success" : "status-error")}`,
                }, state.uploadStatus)
              : null,
          ]),

          // Documents card
          h("div", { class: "card" }, [
            h("h2", `Documents (${state.documents.length})`),
            state.documents.length === 0
              ? h("div", { class: "empty" }, "No documents uploaded yet")
              : h("ul", { class: "doc-list" },
                  state.documents.map((d) =>
                    h("li", [
                      h("span", d.title),
                      h("span", { style: "display:flex;gap:6px" }, [
                        h("span", { class: "badge" }, d.document_type),
                        h("span", { class: `badge ${d.status === "indexed" ? "badge-green" : ""}` }, d.status),
                      ]),
                    ])
                  )
                ),
          ]),
        ]),
      ]);
  },
}).mount("#app");
