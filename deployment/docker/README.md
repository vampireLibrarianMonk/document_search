# Docker Compose - User Operations

Once the stack is running, here's how to use it.

## URLs

| Service       | HTTP                       | HTTPS                      |
| ------------- | -------------------------- | -------------------------- |
| App           | http://localhost:5173      | https://app.localhost      |
| API Docs      | http://localhost:8000/docs | https://api.localhost/docs |
| BookStack     | http://localhost:6875      | -                          |
| MinIO Console | http://localhost:9001      | -                          |

## Commands

```bash
make up          # Start all services (HTTP)
make up-https    # Start all services (HTTPS)
make down        # Stop everything
make ps          # Show running services
make logs        # Tail all logs
make build       # Rebuild images without starting
```

## Uploading Documents

1. Open the app in your browser
2. Pick files or select a folder
3. Click Upload and watch the progress log
4. Documents are auto-categorized and indexed

## Searching

1. Type your query in the search bar
2. Hit Enter or click Search
3. Click any result title to open the original file

## Asking Questions

1. Switch to "Ask AI" mode
2. Type a question in plain English
3. Get an answer with citations from your documents

## Creating Documents

1. Switch to "Create" tab
2. Describe what you want (e.g., "Fill out an exterior modification form for a roof replacement")
3. Optionally select specific source documents
4. Pick output format (Markdown, Word, PDF, Image, PowerPoint)
5. Click Generate, then Preview or Download

## Gap-to-Email

1. Switch to "📧 Gap-to-Email" tab
2. Select a form document (e.g., an HOA application)
3. Optionally add context documents (e.g., architectural standards)
4. Add vendors with their name, contact, and relevant documents
5. Optionally paste an example email to match tone
6. Click "Analyze Gaps & Generate Emails"
7. Copy the generated emails and send to each vendor

## Managing Documents

- Click 👁 to view extracted text
- Click document title to download the original file
- Click ✕ to delete a document
- Click "Clear All" to remove everything

## Settings

- **Service Health**: check connectivity to all services
- **Configuration**: change models, region, BookStack/Confluence credentials
- **Token Usage**: track API costs

## BookStack

- Login: `admin@admin.com` / `password`
- Documents uploaded through the app are auto-organized in BookStack by category
- Sync from BookStack: `curl -X POST http://localhost:8000/sources/bookstack/sync`

### Setting Up BookStack API Token

1. Open BookStack at http://localhost:6875
2. Log in with `admin@admin.com` / `password`
3. Click your avatar (top right) > "Edit Profile"
4. Scroll to "API Tokens" > "Create Token"
5. Copy the Token ID and Token Secret
6. Go to the app Settings > Configuration and paste them into BookStack Token ID and BookStack Secret
7. Click Save

After this, documents you upload through the app will automatically appear in BookStack organized by category.
