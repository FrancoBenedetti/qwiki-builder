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

## Authoring Best Practices for Qwiki

1. **Title H1**: Start every Markdown file with `# Document Title`.
2. **Mermaid Diagrams**: Visual flowcharts (`flowchart TD`) and sequence diagrams (`sequenceDiagram`).
3. **Structured Tables**: Use markdown tables for data, specs, and checklists.
4. **Zero-JS Print**: Ensure clean rendering without bespoke JavaScript or external style dependencies.
5. **Validation First**: Always run `qwiki-builder validate` before executing `qwiki-builder publish`.
