# Image Metadata in Health Tab

## Goal

Display Docker image metadata (tag, build date, git commit hash) for the backend and frontend services in the Settings > Service Health tab.

## Requirements

### Build-Time: Inject metadata into images

1. Pass build args (`IMAGE_TAG`, `BUILD_DATE`, `GIT_HASH`) during `docker build`
2. Store them as `LABEL`s in each Dockerfile and as environment variables available at runtime
3. Update `docker-compose.yml` build sections to forward these args
4. Add a `Makefile` target (or update existing `up` target) that computes the values:
   - `IMAGE_TAG` — git tag or `latest`
   - `BUILD_DATE` — ISO 8601 UTC timestamp
   - `GIT_HASH` — short SHA of HEAD

### Backend: Expose metadata in health check response

1. Read `IMAGE_TAG`, `BUILD_DATE`, `GIT_HASH` from environment variables at startup
2. Add an `"app"` entry to the `/admin/health-check` response:
   ```json
   {
     "app": {
       "status": "ok",
       "tag": "v1.2.0",
       "build_date": "2026-05-10T22:00:00Z",
       "git_hash": "a1b2c3d"
     }
   }
   ```
3. If variables are missing (local dev), return `"dev"` / `"unknown"` defaults

### Frontend: Display metadata in health tab

1. Render the `app` entry alongside existing service checks (AWS, Postgres, OpenSearch, etc.)
2. Show tag, build date, and git hash as a row in the health table
3. No special styling needed — match existing health check row format

## Acceptance Criteria

- [ ] `docker inspect` on built images shows `IMAGE_TAG`, `BUILD_DATE`, `GIT_HASH` labels
- [ ] `/admin/health-check` response includes `app` object with `tag`, `build_date`, `git_hash`
- [ ] Health tab in the UI displays the three metadata fields
- [ ] Running locally without Docker shows fallback values without errors
