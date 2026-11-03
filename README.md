# 🚀 Qwiki Builder

> **Generalised CLI, Python Engine, and AI Agent Workflow for Automated Creation and Remote Deployment of Online Documentation Suites to [Standalone Qwiki](https://github.com/qwiki-wiki/standalone-qwiki).**

[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Zero External Dependencies](https://img.shields.io/badge/dependencies-0%20external-brightgreen.svg)]()
[![Qwiki Compatible](https://img.shields.io/badge/qwiki-v1.0+-orange.svg)](https://github.com/qwiki-wiki/standalone-qwiki)

---

## 📖 Overview

**Qwiki Builder** turns raw documents, specifications, user guides, standard operating procedures, and engineering notes into production-ready online documentation portals hosted on **Standalone Qwiki**.

This framework was born from the production rollout of the **MoBioplus Agricultural & GeoCRM User Documentation** (`wiki.mobioplus.co.za/user-docs`), where 24 canonical technical and operational chapters were systematically published and synced via Qwiki's headless publishing REST API.

**Qwiki Builder generalises this entire workflow into an open-source toolchain** that can be used directly from the command line, imported as a Python library, incorporated into CI/CD pipelines, or driven autonomously by AI Agents (Antigravity, Claude, Cursor, Copilot, Gemini).

---

## 📚 Supported Documentation Suites & Templates

Qwiki Builder ships with production-grade templates tailored to standard business and industrial documentation needs:

| Template Preset | Use Case | Included Default Sections |
| :--- | :--- | :--- |
| **`user-guide`** | SaaS, Mobile Apps, Enterprise Platforms | Welcome, Quick Start, Dashboard, Resource Management, FAQ |
| **`equipment-manual`** | Machinery, Hardware, Medical, Electronics | Architecture, Technical Data, Safety (LOTO), Operation, Maintenance |
| **`quality-manual`** | ISO 9001, QA/QC Systems, Compliance | Quality Policy, Leadership Roles, Core Processes, Auditing & CAPA |
| **`safety-handbook`** | EHS, OSHA, Factory / Field Workplaces | Golden Rules, Emergency Evacuation, Mandatory PPE, Incident Reporting |
| **`sop`** | Standard Operating Procedures Library | SOP Authoring Standard, Numbering, Change Control, Handover Protocols |
| **`blank`** | Custom / Bespoke Portals | Clean foundation for custom information architectures |

---

## ✨ Key Features

- **Zero External Dependencies**: Engineered entirely on the Python Standard Library (`urllib`, `json`, `argparse`, `pathlib`, `re`). Zero `pip` headaches or dependency bloat.
- **Pre-Built Industry Templates**: Scaffold rich, compliant manual structures in seconds with `qwiki-builder init`.
- **Pre-Flight Validation Engine**: Validates missing files, broken image paths, duplicate slugs, undeclared categories, and Mermaid diagram formatting *before* touching the remote server.
- **Automatic Asset Upload & URL Rewriting**: Recursively uploads screenshots and diagrams (`.png`, `.jpg`, `.webp`, `.svg`, `.gif`) via Qwiki's multipart API, caching uploads and automatically rewriting relative Markdown paths to remote URLs.
- **In-Place Updates & Stable Slugs**: Preserves document slugs, internal cross-links, and cryptographic share keys across continuous edits.
- **Automated Deduplication & Clean Reload**: Intelligently identifies and deletes accidental remote chapter duplicates and suffixed slugs (`doc-1`, `doc-2`), or performs a pristine purge-and-reload.
- **Multi-Profile Configuration**: Store and switch between multiple remote wiki environments (`production`, `staging`, `safety-wiki`) globally in `~/.config/qwiki-builder/config.json`.
- **First-Class AI Agent Support**: Comes pre-packaged with [`AGENTS.md`](AGENTS.md) and an Antigravity Skill (`skills/qwiki-doc-builder/SKILL.md`) for autonomous agents to research, author, validate, and deploy complete manuals.

---

## ⚡ Quick Start

### 1. Installation

You can install Qwiki Builder via `pip`, run it directly from checkout, or install it system-wide:

```bash
# Clone the repository
git clone https://github.com/FrancoBenedetti/qwiki-builder.git
cd qwiki-builder

# Option A: Install into your active Python environment
pip install .

# Option B: Run directly from checkout
./bin/qwiki-builder --help

# Option C: Global system install (links CLI to ~/.local/bin and installs Agent Skill)
./scripts/install-global.sh

# Option D: Install directly from GitHub
pip install git+https://github.com/FrancoBenedetti/qwiki-builder.git
```

### 2. Scaffold a New Manual Project

Create a new directory and scaffold your desired template:

```bash
# Scaffold an Industrial Equipment Manual
qwiki-builder init my-titan-manual --template equipment-manual --name "Titan 5000 Operator Manual"

cd my-titan-manual
```

The resulting directory structure:

```
my-titan-manual/
├── qwiki-project.json     # Project manifest & category hierarchy
├── README.md              # Project quick reference
└── docs/
    ├── assets/            # Screenshots, diagrams, and PDFs
    ├── 01-specifications/ # Technical data and system overview
    ├── 02-safety/         # Safety precautions and LOTO protocols
    ├── 03-operation/      # Startup sequence and controls
    └── 04-maintenance/    # Preventive inspection schedule
```

### 3. Configure Remote Qwiki Connection

Save your target wiki's URL and API key into your global configuration profile:

```bash
# Store credentials in ~/.config/qwiki-builder/config.json
qwiki-builder config --url https://wiki.example.com/manuals --key qwk_llm_your_secret_key
```

*(Alternatively, you can provide `wiki_url` and `api_key` in `qwiki-project.json`, or via environment variables `QWIKI_URL` and `QWIKI_API_KEY`.)*

### 4. Validate & Publish

```bash
# 1. Run local pre-flight checks
qwiki-builder validate

# 2. Preview publish actions without modifying remote server
qwiki-builder publish --dry-run

# 3. Synchronize live to remote Qwiki
qwiki-builder publish
```

---

## 💻 CLI Command Reference

### `qwiki-builder init [path] [--template TYPE] [--name TITLE]`
Scaffolds a new project with starter markdown documents and `qwiki-project.json`.
- `--template`: `user-guide` (default), `equipment-manual`, `quality-manual`, `safety-handbook`, `sop`, or `blank`.
- `--name`: Display title for the manual.
- `--url`: Remote wiki endpoint.
- `--key`: Remote API key.

### `qwiki-builder config`
Manages global connection profiles in `~/.config/qwiki-builder/config.json`.
- `qwiki-builder config --list`: Show all saved profiles.
- `qwiki-builder config --profile production --url <url> --key <key>`: Add or update a profile.
- `qwiki-builder config --delete --profile <name>`: Remove a profile.
- `qwiki-builder config --show-path`: Print location of global configuration.

### `qwiki-builder validate [manifest]`
Runs local pre-flight checks:
- Verifies all declared document files exist on disk.
- Validates category references and slug uniqueness.
- Checks local image references and flags missing files.
- Inspects Mermaid diagram formatting for common syntax issues.

### `qwiki-builder publish [manifest] [--dry-run] [--reload]`
Synchronizes the entire documentation suite:
- Creates missing categories on the remote wiki automatically.
- Pre-uploads image assets from `assets_dir` and rewrites paths in Markdown.
- Publishes or updates documents in-place using stable slugs.
- `--dry-run`: Simulates the publication without network mutations.
- `--reload`: Purges existing chapters in target categories and performs a pristine reload.

### `qwiki-builder update <file-or-slug> [manifest]`
Updates a single document in place on Qwiki without re-publishing the rest of the suite.

```bash
qwiki-builder update docs/01-specifications/01-system-overview.md
```

### `qwiki-builder upload-assets [manifest]`
Uploads all images and media assets located in `assets_dir` to Qwiki.

### `qwiki-builder list [manifest] [--book-id ID]`
Queries the remote Qwiki API, lists registered chapters, and highlights duplicate titles or suffixed slugs.

### `qwiki-builder dedup [manifest] [--dry-run]`
Scans the remote wiki for duplicates (e.g., chapters with identical titles or suffixed slugs like `overview-1`) and safely removes them.

### `qwiki-builder reload [manifest]`
Cleanly purges all chapters under the project's categories on the remote wiki and re-uploads all canonical documents.

### `qwiki-builder delete <slug> [manifest] [--book-id ID]`
Deletes a specific chapter from the remote wiki by slug.

---

## 🗂️ Manifest Schema (`qwiki-project.json`)

```json
{
  "name": "Titan 5000 Operator Manual",
  "slug": "titan-5000-manual",
  "version": "1.0.0",
  "doc_type_preset": "equipment-manual",
  "description": "Comprehensive operation and safety manual.",
  "wiki_url": "https://wiki.example.com/manuals",
  "docs_dir": "docs",
  "assets_dir": "docs/assets",
  "default_status": "published",
  "public_shareable": true,
  "categories": [
    {
      "id": "specifications",
      "title": "System Specifications",
      "description": "General machine architecture and parameters"
    },
    {
      "id": "safety",
      "title": "Safety & Warnings",
      "description": "Mandatory PPE, emergency stops, and lockout/tagout"
    }
  ],
  "documents": [
    {
      "file": "01-specifications/01-system-overview.md",
      "category": "specifications",
      "slug": "equipment-system-overview",
      "title": "Equipment Overview & Architecture",
      "status": "published"
    },
    {
      "file": "02-safety/01-safety-precautions.md",
      "category": "safety",
      "slug": "equipment-safety-warnings-loto",
      "title": "Safety Precautions & LOTO Protocols",
      "status": "published"
    }
  ]
}
```

> [!TIP]
> **Auto-Discovery Mode**: If you omit the `"documents"` array or leave it empty, `qwiki-builder` automatically discovers all `.md` and `.html` files in `docs_dir`, using subdirectories as category IDs and extracting H1 headings as document titles!

---

## 🔐 Credential Resolution Priority

Qwiki Builder resolves the target Wiki URL and API Key in the following order:

1. **Explicit CLI flags**: `--url` and `--key`
2. **Explicit CLI profile**: `--profile <name>`
3. **Project manifest**: `wiki_url` and `api_key` in `qwiki-project.json`
4. **Environment variables**: `QWIKI_URL` and `QWIKI_API_KEY`
5. **Global default profile**: `~/.config/qwiki-builder/config.json`

---

## 🐍 Python Library SDK

You can embed Qwiki Builder directly into your Python tools, web services, or data pipelines:

```python
from pathlib import Path
from qwikibuilder import QwikiClient, QwikiProjectManifest, QwikiPublisher, ProjectValidator

# Load project
manifest = QwikiProjectManifest.load(Path("qwiki-project.json"))

# Validate
validator = ProjectValidator(manifest)
report = validator.validate()
if not report.is_valid:
    print(f"Validation errors: {report.errors}")
    exit(1)

# Connect and deploy
client = QwikiClient(base_url="https://wiki.example.com/docs", api_key="qwk_llm_...")
publisher = QwikiPublisher(manifest, client)

# Publish all chapters
result = publisher.publish_all()
print(f"Successfully published {result['synced']}/{result['total']} chapters.")
```

---

## 🤖 AI Agent Workflow & Autonomous Authoring

Qwiki Builder is designed to be paired with AI Agents (Antigravity, Claude, Cursor, Copilot, Gemini CLI).

- Read [`AGENTS.md`](AGENTS.md) for full agent operating instructions.
- An Antigravity / Agent Skill definition is available at [`skills/qwiki-doc-builder/SKILL.md`](skills/qwiki-doc-builder/SKILL.md).

Agents can autonomously:
1. Interview users or ingest raw specifications, PRDs, and codebase docs.
2. Select the right template preset (`equipment-manual`, `quality-manual`, etc.).
3. Generate compliant Markdown with Mermaid diagrams and structured tables.
4. Run `qwiki-builder validate` to check for syntax or link errors.
5. Deploy to Standalone Qwiki via `qwiki-builder publish`.

---

## 🔄 CI/CD Automation (GitHub Actions)

Deploy documentation automatically on every `git push`:

Create `.github/workflows/deploy-docs.yml`:

```yaml
name: Deploy Documentation to Qwiki

on:
  push:
    branches: [main]
    paths:
      - 'docs/**'
      - 'qwiki-project.json'

jobs:
  deploy-qwiki:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Install Qwiki Builder
        run: pip install git+https://github.com/FrancoBenedetti/qwiki-builder.git

      - name: Validate Documentation
        run: qwiki-builder validate

      - name: Publish to Qwiki
        env:
          QWIKI_URL: ${{ secrets.QWIKI_URL }}
          QWIKI_API_KEY: ${{ secrets.QWIKI_API_KEY }}
        run: qwiki-builder publish
```

---

## 🧪 Testing

Run the full automated test suite:

```bash
python3 -m unittest discover tests -v
```

---

## 📄 License

Released under the [MIT License](LICENSE). Built for the global Qwiki and Antigravity community.
