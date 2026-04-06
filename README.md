# House Document Search

This is a tool that helps you search through house-related documents like HOA rules, inspection reports, closing paperwork, insurance policies, and anything else that comes with buying or owning a home. Instead of digging through a pile of PDFs and Word docs trying to find that one paragraph about fence height limits or what the inspector said about the roof, you can upload your files and just search or ask questions in plain English. The app breaks your documents into smaller pieces, scores them for relevance, and gives you back the most useful snippets along with where they came from. Think of it like having a personal assistant who has actually read all your paperwork.

## How to Use It

### Uploading Documents

1. Open the app in your browser at `http://localhost:5173` (or `https://app.localhost` if running with HTTPS)
2. In the "Upload Document" section, click the file picker and choose a PDF, Word doc, text file, or markdown file
3. Click "Upload" and wait for the confirmation message
4. Your document will appear in the "Documents" list at the bottom of the page

### Searching

1. Make sure the "Search" toggle is selected (it is by default)
2. Type what you are looking for in the search bar, something like "rules about sheds" or "roof condition"
3. Hit Enter or click the Search button
4. Results show up below with the document name, type, relevance score, and a snippet of the matching text

### Asking Questions

1. Click the "Ask AI" toggle next to the search bar
2. Type a question like "What does the inspection say about the foundation?"
3. Hit Enter or click Ask
4. You will get a plain English answer along with citations showing exactly which parts of which documents the answer came from

### Supported File Types

- PDF (.pdf)
- Word documents (.docx)
- Plain text (.txt)
- Markdown (.md)

## Running the App

There are three ways to run it: locally without containers, with Docker Compose over HTTP, or with Docker Compose over HTTPS. See [README-SETUP.md](README-SETUP.md) for full setup instructions.

Quick start if you already have Python and Node installed:

```bash
source .venv/bin/activate
make dev-all
```

Or with Docker:

```bash
make up
```

## API

The backend has a full REST API if you want to interact with it directly. Once the backend is running, visit `http://localhost:8000/docs` (or `https://api.localhost/docs` with HTTPS) for the interactive API documentation.
