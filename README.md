# House Document Search

This is a tool that helps you search through house-related documents like HOA rules, inspection reports, closing paperwork, insurance policies, and anything else that comes with buying or owning a home. Instead of digging through a pile of PDFs and Word docs trying to find that one paragraph about fence height limits or what the inspector said about the roof, you can upload your files and just search or ask questions in plain English. The app breaks your documents into smaller pieces, scores them for relevance, and gives you back the most useful snippets along with where they came from. Think of it like having a personal assistant who has actually read all your paperwork.

When you upload a document, the app automatically reads the content, figures out what kind of document it is (closing disclosure, HOA bylaws, appraisal, etc.), and files it into the right category. You can also connect it to BookStack (a local wiki) or Confluence Cloud to sync documents from there instead of uploading manually.

## How to Use It

### Uploading Documents

1. Open the app in your browser at `http://localhost:5173` (or `https://app.localhost` if running with HTTPS)
2. In the "Upload Documents" section, pick one or more files (PDF, Word, text, or markdown)
3. Click "Upload" and wait for the confirmation
4. Documents are automatically categorized and appear in the list at the bottom

### Searching

1. Make sure the "Search" toggle is selected (it is by default)
2. Type what you are looking for in the search bar, something like "rules about sheds" or "roof condition"
3. Hit Enter or click the Search button
4. Results show up below with the document name, type, relevance score, and a snippet of the matching text

### Asking Questions

1. Click the "Ask AI" toggle next to the search bar
2. Type a question like "What is the email address for my HOA?"
3. Hit Enter or click Ask
4. You will get a plain English answer powered by Amazon Bedrock along with citations showing exactly which documents the answer came from

### Syncing from BookStack

BookStack is a local wiki that runs alongside the app. You can organize your documents there and sync them into the search system.

1. Open BookStack at `http://localhost:6875` (default login: `admin@admin.com` / `password`)
2. Create a book, add pages, and attach your PDFs
3. Generate an API token in your BookStack profile settings
4. Add the token to `infra/docker/compose/local.env`
5. Sync: `curl -X POST http://localhost:8000/sources/bookstack/sync`

### Syncing from Confluence Cloud

When you are ready to move to Confluence Cloud, the connector is built and ready.

1. Sign up at https://www.atlassian.com/software/confluence (free tier works)
2. Create a space, upload your PDFs as page attachments
3. Generate an API token at https://id.atlassian.com/manage-profile/security/api-tokens
4. Add your site URL, email, and token to `infra/docker/compose/local.env`
5. Sync: `curl -X POST http://localhost:8000/sources/confluence/sync -H 'Content-Type: application/json' -d '{"space_keys":["YOUR_SPACE"]}'`

### Supported File Types

- PDF (.pdf)
- Word documents (.docx)
- Plain text (.txt)
- Markdown (.md)

## Running the App

There are three ways to run it: locally without containers, with Docker Compose over HTTP, or with Docker Compose over HTTPS. See [README-SETUP.md](README-SETUP.md) for full setup instructions.

Quick start with Docker:

```bash
make up
```

Or locally:

```bash
source .venv/bin/activate
make dev-all
```

## API

The backend has a full REST API. Once running, visit `http://localhost:8000/docs` (or `https://api.localhost/docs` with HTTPS) for the interactive documentation.
