# Settings page + frontend plugin system

Status 2026-09-19: S1–S3 live-tested OK (user), committed. ROOT Users built, awaiting live test. Next: R4 (Recycling_Agent_Tools_Plan.md).
Precedes R3b in `Recycling_Agent_Tools_Plan.md` (R3b = S3 here).

## Model (agreed)
- Shell: Navbar (existing) + settings sidebar + main panel. URL-driven: `/settings/:category/:section` (renamed from `/setting`; bare `/settings` → first visible section).
- Section list: `{category, id, labelKey, minRole, component}`. Sidebar = list grouped by category, filtered by role. Core + plugin sections same shape.
- Category = grouping (who OWNS it); `minRole` per section = who SEES it. Two axes, deliberately separate.
- Data: each section fetches its own. CORE sections share one form engine over `GET/PATCH/DELETE /settings`.
- Categories: CORE, ROOT, PLUGIN. **No ADMIN category for now** (user decision). Empty category not rendered.

## CORE (S1)
General: system_prompt_name (select), log_level (session-only badge) | LLM: temperature, top_p, top_k, max_tokens, context_window | Memory: summary_token_threshold, max_summary_chars, max_unsummarized_messages, max_context_history_messages, min_retained_raw_messages, max_checkpoint_messages | Streaming: sse_heartbeat_seconds, sse_queue_maxsize.
- One Save per section (not per-field autosave): memory fields interlock (min_retained < max_unsummarized ≤ max_context_history; max_tokens < context_window) → per-field save hits rejected intermediate states. PATCH = changed keys only; backend rejects whole batch; 422 detail shown verbatim.
- Per-field Reset = `DELETE /settings/{key}` (can also 422 on cross-field).
- Labels/help/input kind in frontend (i18n lives there); validation stays backend.
- system_prompt_name = select over `GET /settings/prompt-sets` (complete sets only). Why: `resolve_prompt_set` silently falls back to `default/` on a missing set → typo = silent persona switch.
- Language/theme stay in navbar: per-browser, not server settings.

## ROOT (later slice, needs backend)
Users & roles: root CRUDs all users, grants elevated role. Delete = hard delete for now; **"ban" is the right semantics** (user noted) — revisit: ban keeps rows/conversations, blocks login. `ACTION_MANAGE_ADMINS` in `app/authentication/authorization.py` exists, unused.

## Frontend plugin system (S2) — decided: backend decides existence, frontend holds code
- Why: one gate (`EXCLUDED_TOOL_PLUGINS`); a second frontend list = fail-open twice (recycle page on job-app deployment). Frontend hiding is cosmetic; backend must refuse anyway.
- Backend `GET /plugins` → loaded names (after exclusion + failed initialize).
- Frontend `ui/src/plugins/<name>/index.ts` → `FrontendPlugin {name, settingsSections?, chatSidebar?}`; static registry `ui/src/plugins/index.ts`; `usePlugins()` = registry ∩ backend list. Name = backend folder name exactly (`recruitment`, not "document").
- Slots added only when a plugin needs one: `chatSidebar` (blank forms, currently hardcoded `Sidebar.tsx` BLANK_FORMS), `settingsSections`.

## S3 = R3b
- `ToolPlugin.router_factory: Callable[[ToolContext], APIRouter] | None`, mounted by server.py under `/plugins/<name>/`; CLI ignores. Lock-in: FastAPI in plugin `routes.py` only; framework-neutral handler layer rejected as overengineering.
- Move `/documents/blank/{doc_type}` into recruitment plugin (reverses its "registered regardless" docstring on purpose: delete-folder-removes-feature). Also fixes a live violation: `app/runtime/server.py` does `from app.plugins.recruitment.blank import BLANK_DOCUMENTS` → deleting the recruitment folder breaks the server.
- Recycling Catalog settings section; `/recycle show_catalog` links/redirects there.

## S1 as built (2026-09-19)
- BE: `list_prompt_sets()` in `app/config/prompts.py` (complete sets only); `GET /settings/prompt-sets` (any signed-in user, like GET /settings).
- FE: `ui/src/settings/{sections.ts, SettingsSidebar.tsx, RuntimeSettingsForm.tsx, CoreSections.tsx}`, `layout/SettingsPage.tsx` (old `SettingPage.tsx` deleted), `hooks/useSettings.ts`, `assets/css/settings.css`; i18n `nav.setting`→`nav.settings`, new `settings.*` (field keys = backend names).
- Section list lives in `sections.ts`, components in `CoreSections.tsx`: react-refresh/only-export-components forbids mixing.
- Form: edits-only state (unedited fields read the query); integer field sends non-`^\d+$` text as string (else Python int(1.5)→1 silently); `noValidate`; section keyed by path → switching drops unsaved edits (no leave-guard).
- Non-admin on /settings → redirect `/`; unknown section → first visible.
- Verified: tsc -b, eslint src clean; routes present via create_api(Application()). Live test = user.

## S2 as built (2026-09-19)
- BE: `load_tools` → `LoadedTools(tools, plugins, failed)`; app folds `failed` into `excluded_plugins` (fixed gap: factory-failed plugin still got commands + prompt; startup log `loaded=` listed it). `Application.loaded_plugins`; `GET /plugins` → `{"plugins": [...]}` (any signed-in user).
- FE: `ui/src/plugins/{types.ts, index.ts, recruitment/{index.ts, BlankForms.tsx, blankForms.css, messages.ts}}`, `hooks/usePlugins.ts`. `FrontendPlugin {name, messages?, chatSidebar?}`. Sidebar renders `chatSidebar` slots; BLANK_FORMS, `blankDocumentUrl` (client.ts), `.sidebar-form*` CSS, `sidebar.blankForms` i18n all moved into plugin.
- Plugin i18n: `plugins/index.ts` imports `../i18n` (forces init first; init() replaces store) then `addResourceBundle(lang, "translation", {plugins:{[name]:msgs}}, deep=true)`. Keys `plugins.<name>.<key>`.
- `API_BASE_URL` exported from client.ts for plugins.
- Gate fails CLOSED (nothing until /plugins answers); staleTime Infinity.
- `settingsSections` slot deliberately NOT added yet (S3 = first user). S3 must: wait for `usePlugins().isPending` before SettingsPage redirects, else a deep link to a plugin section bounces to General.
- Local `.env` excludes `recruitment` → blank forms should vanish = live test.

## S3 as built (2026-09-19)
- Contract: `RouteContext(tool, current_user, require_admin)`; `ToolPlugin.router_factory: Callable[[RouteContext], APIRouter] | None` (APIRouter under TYPE_CHECKING only). `loader.load_routers(ctx, excluded)` → `{name: router}`, factory failure logged+skipped. `create_api` mounts `/plugins/<name>` with `Depends(current_user)` on all; needs `Application.tool_context` + `.excluded_plugins` (set in initialize). FastAPI 0.141: included router = one `_IncludedRouter` in app.routes (no per-route paths to list) → verify with TestClient, not route listing.
- Moved: `/documents/blank/{doc_type}` → recruitment `routes.py` `/plugins/recruitment/blank/{doc_type}`; `server._attachment_header` → `app/utils/filenames.attachment_disposition`; server.py no longer imports any plugin.
- Recycling: `CatalogRepository.page(search, visual_class, excluded, offset, limit)` → `CatalogPage(total, rows(dict, +updated_at), visual_classes)`; ILIKE with %/_ escaped; `EvidenceRepository.by_item(item_ids=None)`. `GET /plugins/recycling/catalog` admin, limit ≤200.
- FE slots added: `settingsSections` (forced category plugin, id `<plugin>-<id>`), `commandRedirects {namespace, subcommands, section}`. `useCommandRedirect()` in hooks/usePlugins.ts; Chat.handleSubmit: bare cmd, no attachments, canSee → navigate, never sent. SettingsPage waits `plugins.isPending`.
- `request()` exported from client.ts for plugins. `.settings-panel` max-width moved to `.settings-form` (catalog table needs width).
- Catalog.tsx: debounced search 300ms, class/status filters (reset offset), 50/page, keepPreviousData (dimmed), evidence chips → overlay `<img src=/files/id>` (img ignores Content-Disposition: attachment) + download link, Esc closes. Read-only.
- **nginx fix**: API location regex lacked `plugins` (S2's `/plugins` would have hit SPA index.html in prod → plugin UI silently gone); now `auth|commands|conversations|files|plugins|settings|health` (`documents` dropped). deploy/README diagram updated.
- Verified: tsc, eslint, vite build; TestClient: plugin route 401 unauth, 404 when excluded/unknown; catalog 403 user, 422 limit=999; page() SQL all filter branches vs real DB (empty catalog → no row-shape check).
- Follow-up fixes (2026-09-19, user): (1) tool `recycle_show_catalog` → runner `catalog_link` (commands.py; `CatalogRepository.counts()`; `CATALOG_PAGE_PATH="/settings/plugin/recycling-catalog"` = FE contract) posts link+counts; `tools.build(runner_key=)`; typed cmd/CLI keep table. Markdown.tsx: root-relative non-`//` href → router `<Link>`. (2) TableScroll mechanics moved chat.css → `assets/css/tableScroll.css` imported by component (were scoped `.message-content` → no overflow on settings page); catalog cells nowrap + bordered like chat; `.settings-main {min-width:0}` (flex item else grows to table width); sticky th dropped (scroll container breaks it). (3) recruitment settings section `blank-forms` (BlankFormsSection.tsx, download buttons); shared `forms.ts` (BLANK_FORMS, blankDocumentUrl).
- Not done / open: No thumbnails (full-size images; would need resize endpoint). Catalog edits in UI not built.

## ROOT Users as built (2026-09-19)
- BE: `app/authentication/user_admin.py` `UserAdminService` (list/create/update/delete; errors UserNotFound→404, EmailTaken/RootProtected→409, other UserAdminError→422 — never 403, SPA's AuthProvider turns any 403 into the CSRF reload screen). `make_require_root` (dependencies.py, `can(ACTION_MANAGE_ADMINS)`). `UserRepository.list_all/update/delete` (delete: one txn reads files' storage_keys (user_id OR user's conversations) then DELETE users → cascade; service deletes bytes after, best effort). Routes `/users` GET/POST, `/users/{id}` PATCH/DELETE in server.py; `_serialize_user` omits password_hash. nginx regex + deploy/README gain `users`.
- Rules: assignable roles user/admin only; root row not editable/deletable (env + --seed-admin); pw change → `sessions.delete_for_user`; role change needs nothing (session lookup re-reads users row).
- FE: `settings/UsersSection.tsx` (ROOT category, minRole root), `hooks/useUsers.ts` (invalidate on change), client fns, types `ManagedUser/AssignableRole/Create|UpdateUserRequest`; i18n `settings.users.*`; CSS `.users-*` in settings.css.
- Verified: service vs dev DB with throwaway `zz-test-*@example.invalid` (create, dup, update+pw sign-out, root edit/delete refused, list order, delete, delete-again 404); HTTP: user/admin 403, root 200, no hash in body. tsc/eslint/vite build clean.
- Delete completeness (checked vs information_schema 2026-09-19): all FKs CASCADE; only LangGraph `checkpoints/checkpoint_blobs/checkpoint_writes` (thread_id text, no FK) escaped → `UserAdminService(delete_thread=checkpointer.adelete_thread)`, built in `Application.initialize()` after checkpointer; `UserRepository.delete` → `DeletedUser(storage_keys, conversation_ids)`. E2E verified: conv/msg/file/checkpoint/checkpoint_writes all 0 after, bytes deleted.
- Open: "ban" instead of hard delete (user's stated long-term semantics); delete of a user mid-generation not handled; no self-service password change for non-root.

## Slices
S1 shell + CORE + prompt-sets endpoint → S2 `/plugins` + FE registry + blank forms gated → S3 router_factory + catalog page (R3b) → ROOT users & roles.
