#!/usr/bin/env bash
# Builds the iPad app into docs/model/device/ for the 3D model page: the real app in its demo (mock) mode, with
# sim/shim.js joining its panel socket, camera, microphone and printer to the page around it.
# Run it after changing the app; the page shows a still screenshot until device/ exists. device/ is not committed.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
cd "$here/../../app"
npm run gen >/dev/null
npx vite build --base ./ --outDir "$here/device" --emptyOutDir --logLevel warn
rm -f "$here/device/song.html" "$here"/device/assets/song-*
cp "$here/sim/shim.js" "$here/device/shim.js"
mkdir -p "$here/device/photos"
cp "$here/sim/photos/"*.jpg "$here/device/photos/"
# the shim has to run before the app's module script
python3 - "$here/device/index.html" <<'PY'
import sys
path = sys.argv[1]
html = open(path, encoding="utf-8").read()
if "shim.js" not in html:
    html = html.replace("<head>", '<head>\n    <script src="./shim.js"></script>', 1)
open(path, "w", encoding="utf-8").write(html)
PY
echo "built $(find "$here/device" -type f | wc -l | tr -d ' ') files in docs/model/device"
