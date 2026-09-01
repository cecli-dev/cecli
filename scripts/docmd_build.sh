#!/bin/bash
# Build the cecli website with docmd.
#
# Produces a deployable site in cecli/website/_site:
#   _site/index.html       marketing homepage
#   _site/docs/            docmd-generated documentation
#   _site/assets/          styles.css + static assets
#   _site/install.sh       installers
#   _site/install.ps1
#   _site/share/           shared resources
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WEBSITE="$ROOT/cecli/website"
SITE="$WEBSITE/_site"

cd "$WEBSITE"

# Determine where docmd will write its output (from docmd.config.json "out")
DOCMD_OUT="$(python3 -c "import json;print(json.load(open('docmd.config.json'))['out'])")"
DOCMD_OUT_DIR="$WEBSITE/$DOCMD_OUT"

# Clean the deploy dir before building (docmd may write straight into _site/docs)
rm -rf "$SITE"
mkdir -p "$SITE"

echo "==> Building docs with docmd"
npx -y @docmd/core@0.8.17 build

# 1. Move/copy docmd output into _site/docs
if [ "$DOCMD_OUT_DIR" != "$SITE/docs" ]; then
    echo "==> Moving docmd output into $SITE/docs"
    mv "$DOCMD_OUT_DIR" "$SITE/docs"
fi

# 2. Homepage (strip Jekyll frontmatter)
echo "==> Copying homepage"
awk 'BEGIN{n=0} /^---$/{n++; next} n>=2{print}' index.html > "$SITE/index.html"

# 3. Compile styles.scss -> _site/assets/styles.css
echo "==> Compiling styles.scss"
mkdir -p "$SITE/assets"
awk 'BEGIN{n=0} /^---$/{n++; next} n>=2{print}' assets/styles.scss > /tmp/cecli_styles.scss
npx -y sass --load-path _sass --style=compressed /tmp/cecli_styles.scss "$SITE/assets/styles.css"

# 4. Copy static assets (excluding scss sources and _sass partials)
echo "==> Copying static assets"
find assets -type f ! -name '*.scss' ! -path '*/_sass/*' -exec cp --parents {} "$SITE/" \;

# 5. Installers and shared resources
echo "==> Copying installers and share"
cp install.sh install.ps1 "$SITE/"
cp -r share "$SITE/share"

echo "==> Build complete: $SITE"
