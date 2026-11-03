#!/usr/bin/env bash
# ==============================================================================
# Qwiki Builder Global System Installer
# Installs:
#   1. The 'qwiki-builder' CLI command into ~/.local/bin/
#   2. The 'qwiki-doc-builder' Agent Skill into Antigravity builtin skills
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "================================================================================"
echo "🚀 Installing Qwiki Builder globally on your system"
echo "================================================================================"

# 1. Install CLI script to ~/.local/bin
TARGET_BIN_DIR="${HOME}/.local/bin"
mkdir -p "${TARGET_BIN_DIR}"
ln -sf "${SCRIPT_DIR}/bin/qwiki-builder" "${TARGET_BIN_DIR}/qwiki-builder"
chmod +x "${SCRIPT_DIR}/bin/qwiki-builder"
echo "✅ CLI command linked: ${TARGET_BIN_DIR}/qwiki-builder"

# 2. Install Agent Skill to Antigravity global skills directory
SKILL_DIR="${HOME}/.gemini/antigravity/builtin/skills/qwiki-doc-builder"
if [ -d "${HOME}/.gemini/antigravity/builtin/skills" ]; then
    mkdir -p "${SKILL_DIR}"
    cp -r "${SCRIPT_DIR}/skills/qwiki-doc-builder/"* "${SKILL_DIR}/"
    echo "✅ Agent Skill installed: ${SKILL_DIR}"
fi

echo ""
echo "================================================================================"
echo "🎉 Global installation complete!"
echo "Verify CLI:"
echo "   qwiki-builder --help"
echo "================================================================================"
