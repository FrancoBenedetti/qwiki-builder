# Reference Architecture: MoBioplus User Documentation

This reference project illustrates how the production user documentation deployed to `https://wiki.mobioplus.co.za/user-docs` is modeled inside `qwiki-builder`.

## How It Works

1. **Manifest (`qwiki-project.json`)**:
   - Defines the 7 production categories (`readme`, `01-ops-geocrm`, `01-ops-library`, etc.).
   - Maps each Markdown file to a strict canonical slug (e.g. `geocrm-platform-overview-map-navigation`).
   - Targets the remote wiki endpoint at `https://wiki.mobioplus.co.za/user-docs`.

2. **Publishing with Qwiki Builder**:
   ```bash
   # Set API Key via environment variable or global profile
   export QWIKI_API_KEY="qwk_llm_..."

   # Validate all files and links
   qwiki-builder validate qwiki-project.json

   # Dry-run preview
   qwiki-builder publish qwiki-project.json --dry-run

   # Live synchronization
   qwiki-builder publish qwiki-project.json
   ```

3. **Advantages over Hardcoded Scripts**:
   - Zero hardcoded API keys in scripts or repositories (credentials resolved via profiles, env vars, or local overrides).
   - Pre-deployment validation verifies markdown links, images, and Mermaid diagram formatting before touching the server.
   - Automatic asset upload and URL rewriting.
   - Clean reload and automated deduplication if slug collisions occur.
