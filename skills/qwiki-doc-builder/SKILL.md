---
name: qwiki-doc-builder
description: Automated creation, information architecture design, authoring, and remote publishing of online manuals and documentation suites to Standalone Qwiki.
---

# Qwiki Documentation Builder Skill

Use this skill whenever the user wants to create, structure, author, update, or publish online documentation, user guides, equipment manuals, quality manuals (ISO 9001), safety handbooks, or SOP libraries to a remote or local Standalone Qwiki instance.

## When to Activate

Trigger this skill on mentions of:
- "online manual", "user guide", "equipment manual", "company quality manual", "safety handbook", "SOP library"
- "publish to qwiki", "qwiki builder", "deploy documentation", "qwiki api"
- "sync documentation", "dedup chapters", "reload qwiki docs"

## Quick Capabilities Reference

| Task | Command |
| :--- | :--- |
| **Scaffold new project** | `qwiki-builder init <dir> --template <template>` |
| **Configure credentials** | `qwiki-builder config --url <url> --key <key>` |
| **Validate structure & links** | `qwiki-builder validate` |
| **Preview deployment** | `qwiki-builder publish --dry-run` |
| **Pull live doc, comments & talk** | `qwiki-builder pull <file-or-slug> [--sync-meta]` |
| **Diff local vs live state** | `qwiki-builder diff <file-or-slug>` |
| **Synchronize live** | `qwiki-builder publish` |
| **Update single document** | `qwiki-builder update <file-or-slug>` |
| **Upload media assets** | `qwiki-builder upload-assets` |
| **Inspect remote chapters** | `qwiki-builder list` |
| **Clean duplicates** | `qwiki-builder dedup` |
| **Clean reload** | `qwiki-builder reload` |

## Template Presets

- `user-guide`: Software platforms, web applications, customer onboarding.
- `equipment-manual`: Industrial machinery, medical devices, electronic hardware, automotive equipment.
- `quality-manual`: ISO 9001 / corporate quality management, audit protocols, CAPA.
- `safety-handbook`: Workplace health & safety (EHS / OSHA), emergency response, PPE matrices.
- `sop`: Standard Operating Procedures library with numbered protocols and sign-offs.
- `blank`: Empty project structure for bespoke documentation.

## Authoring & Update Best Practices for Qwiki

1. **Title H1**: Start every Markdown file with `# Document Title`.
2. **Mermaid Diagrams**: Visual flowcharts (`flowchart TD`) and sequence diagrams (`sequenceDiagram`). Quote node labels containing spaces or punctuation.
3. **Structured Tables**: Use markdown tables for data, specs, and checklists.
4. **Zero-JS Print**: Ensure clean rendering without bespoke JavaScript or external style dependencies.
5. **Visual Media & Documentation Assets**: Include UI screenshots (`assets/images/`), generated graphics, and video walkthroughs (`assets/videos/` or YouTube/Vimeo/Loom links) whenever they add value (see the `/Documents/MobioPlus/user-docs` reference deployed to `wiki.mobioplus.co.za/user-docs`). Standalone video links auto-convert into native players.
6. **Validation First**: Always run `qwiki-builder validate` before executing `qwiki-builder publish` or `qwiki-builder update`. Asset references are checked and then automatically uploaded and rewritten to remote Qwiki URLs during publishing.
7. **Live-Published Documents — Pull, Triage & Merge Before Re-Upload**: Never blindly overwrite an already-published chapter from local files. Live users may have edited the page in the Qwiki UI, uploaded `uploads/` media, changed metadata/status, or left feedback in **Comments** (`tool-comments`) and the **Talk Page** (`tool-talk`). Before amending a live document:
   - **Inspect & Pull Live State**: Check `qwiki-builder list` or `qwiki-builder diff <file-or-slug>`, then run `qwiki-builder pull <file-or-slug> [--sync-meta]`. This fetches raw Markdown/HTML (all statuses including `draft`/`review`), records the remote SHA-256 baseline and 3-way merge base in `.qwiki-sync/`, and writes live Comments, Talk topics, and lock state into `.qwiki-sync/feedback/<bookId>__<slug>.feedback.md` without polluting the document body. (If the remote server runs an older Standalone Qwiki without `action=get_doc`, `pull` falls back to `api/llm.php`; for raw HTML or drafts on legacy servers, export from the Qwiki UI.)
   - **Triage Feedback**: Read `.qwiki-sync/feedback/<bookId>__<slug>.feedback.md` (or `.feedback.json`) to identify open change requests, clarifications, and approved Talk proposals.
   - **3-Way Diff & Merge**: If local edits and remote edits diverged cleanly, `pull` auto-merges via `diff3`; if overlapping, it preserves your local file and saves the remote copy to `.qwiki-sync/conflicts/` so you can merge manually while keeping live user edits and `uploads/` media references intact.
   - **Preserve Identity & Concurrency**: Keep `category` (`bookId`), `slug`, and `shareKey` unchanged (Comments and Talk files are keyed by `{bookId}__{slug}`). `qwiki-builder update` / `publish` automatically sends the tracked `expectedSha256` and respects active `LockManager` editor leases (`409 Conflict` / `423 Locked` unless `--force` is passed). Run `qwiki-builder validate` and `qwiki-builder update <file-or-slug> --dry-run` before pushing.
   - **Re-Upload In Place & Close the Loop**: Run `qwiki-builder update <file-or-slug>` (never `qwiki-builder reload` on wikis with live edits or discussions). Because API keys are read-only for discussions, have an authenticated editor/admin post a reply or archive resolved topics on the Talk page/Comments confirming what was updated.

See [`AGENTS.md`](../../AGENTS.md) for the full live-sync protocol and API caveats.
