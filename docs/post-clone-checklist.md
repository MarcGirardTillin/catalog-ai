# Post-Clone Checklist

This checklist covers the local bootstrap of a new application cloned from
this template.

Reading convention:

- `Outside the repo`: actions to perform in GitHub, GitLab, or your password manager
- `Inside the repo`: actions to perform directly in the cloned project

## 1. Project Bootstrap

Inside the repo:

- [ ] Rename visible template values such as `PROJECT_NAME`
- [ ] Check for leftover template branding in documentation and environment variables
- [ ] Adapt `CLAUDE.md` if the cloned project has additional repo-specific rules
- [ ] Identify the sample modules to keep, rename, or remove

## 2. Git Hosting

Outside the repo:

- [ ] Create the empty GitHub or GitLab project
- [ ] Copy the project SSH or HTTPS URL

Inside the repo:

- [ ] Add the remote with `git remote add origin ...`
- [ ] Run `git status --short` before the first commit
- [ ] Confirm that `.env` and local secret files are not tracked
- [ ] Push the initial `main` branch
- [ ] Verify that GitHub Actions or GitLab CI runs the minimal check pipeline

## 3. Database

Inside the repo:

- [ ] Copy/fill in `.env`
- [ ] Populate local PostgreSQL values:
  - `POSTGRES_SERVER`
  - `POSTGRES_DB`
  - `POSTGRES_USER`
  - `POSTGRES_PASSWORD`
- [ ] Store real sensitive values outside the repository

## 4. Local Developer Setup

Inside the repo:

- [ ] Run:
  - `make init`
  - `make db-up`
  - `make migrate-upgrade`
  - `make backend-start`
  - `make frontend-start`
- [ ] Validate the canonical commands:
  - `make check`
  - `make check-back`
  - `make check-front`
- [ ] Use `make doctor` for additional onboarding diagnostics if needed

## 5. First Local Validation

Inside the repo / app behavior:

- [ ] Verify that the Alembic migration runs correctly
- [ ] Verify the frontend starter shell
- [ ] Verify `GET /healthcheck`
- [ ] Verify `GET /version`
- [ ] Verify `GET /example`

## 6. Release Notes

Inside the repo:

- [ ] Keep upcoming changes in `release-notes-techlab.md` under `## Latest Changes`
- [ ] Prepare releases with `make release-techlab version=X.Y.Z`
- [ ] Publish releases by pushing annotated tags named `techlab-vX.Y.Z`
