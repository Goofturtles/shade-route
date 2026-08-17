#!/usr/bin/env bash
# Publish Shade Route to a Hugging Face Space.
#
#   HF_TOKEN=hf_xxx HF_USER=yourname bash deploy/deploy_hf_space.sh
#
# A Space is just a git repository, so this needs no CLI and no SDK — it pushes
# the working tree to it and Hugging Face builds the Dockerfile. Free tier, no
# credit card, and the URL is permanent.
set -euo pipefail

: "${HF_TOKEN:?Set HF_TOKEN — create one at https://huggingface.co/settings/tokens with 'write' access}"
: "${HF_USER:?Set HF_USER to your Hugging Face username}"
SPACE="${HF_SPACE:-shade-route}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "==> Creating the Space (skipped if it already exists)"
curl -sS -X POST "https://huggingface.co/api/repos/create" \
  -H "Authorization: Bearer ${HF_TOKEN}" \
  -H "Content-Type: application/json" \
  -d "{\"type\":\"space\",\"name\":\"${SPACE}\",\"sdk\":\"docker\",\"private\":false}" \
  | head -c 400; echo

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
echo "==> Staging a clean copy in $WORK"

# Ship the committed tree, so whatever is pushed is exactly what is in git.
git archive HEAD | tar -x -C "$WORK"

# A Space is identified by the YAML front-matter in its README, which the
# project README deliberately does not carry — front-matter renders as an ugly
# table on GitHub. So the Space gets its own.
cp README.md "$WORK/PROJECT_README.md"
cp deploy/SPACE_README.md "$WORK/README.md"

cd "$WORK"
git init -q
git checkout -q -b main
git add -A
git -c user.email=deploy@local -c user.name=deploy commit -qm "Deploy Shade Route"

echo "==> Pushing to https://huggingface.co/spaces/${HF_USER}/${SPACE}"
git push -q --force "https://${HF_USER}:${HF_TOKEN}@huggingface.co/spaces/${HF_USER}/${SPACE}" main

echo
echo "Done. The Space is building now (first build takes ~3-5 minutes):"
echo "  https://huggingface.co/spaces/${HF_USER}/${SPACE}"
echo "Once green, the app itself is at:"
echo "  https://${HF_USER}-${SPACE}.hf.space"
