#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "🔄 [PowerPlanner iOS Sync] Starte Synchronisation von Python -> iOS..."

# 1. Dynamische Build-Nummer aus Git-Commits und aktueller Timestamp
BUILD_NUM=$(git -C "$PROJECT_ROOT" rev-list --count HEAD 2>/dev/null || echo "1")
BUILD_TIME=$(date "+%Y-%m-%d %H:%M:%S")

sed -i '' "s/^BUILD_NUMBER = .*/BUILD_NUMBER = \"$BUILD_NUM\"/" "$PROJECT_ROOT/power_planner_flet.py"
sed -i '' "s/^BUILD_TIMESTAMP = .*/BUILD_TIMESTAMP = \"$BUILD_TIME\"/" "$PROJECT_ROOT/power_planner_flet.py"

CONFIG="$PROJECT_ROOT/build/flutter/ios/Flutter/Generated.xcconfig"
if [ -f "$CONFIG" ]; then
    sed -i '' "s/FLUTTER_BUILD_NUMBER=.*/FLUTTER_BUILD_NUMBER=$BUILD_NUM/" "$CONFIG"
    echo "📌 Build-Nummer gesetzt auf: $BUILD_NUM ($BUILD_TIME)"
fi

# 2. Python-Dateiliste für die App
PYTHON_FILES=(
    "power_planner_flet.py"
    "pacing_optimizer.py"
    "gpx_exporter.py"
    "hammerhead_client.py"
    "i18n.py"
    "main.py"
)

# 3. Zielverzeichnisse
STAGING_APP="$PROJECT_ROOT/build/python-app"
SPM_APP="$PROJECT_ROOT/build/flutter/ios/Flutter/ephemeral/Packages/.packages/serious_python_darwin-4.7.0/Sources/serious_python_darwin/Resources/app"
PUB_CACHE_SPM="$HOME/.pub-cache/hosted/pub.dev/serious_python_darwin-4.7.0/darwin/serious_python_darwin/Sources/serious_python_darwin/Resources/app"

echo "📂 Kopiere aktuelle Python-Dateien in Staging ($STAGING_APP)..."
mkdir -p "$STAGING_APP"
for f in "${PYTHON_FILES[@]}"; do
    if [ -f "$PROJECT_ROOT/$f" ]; then
        cp "$PROJECT_ROOT/$f" "$STAGING_APP/"
    fi
done
if [ -f "$PROJECT_ROOT/oetztaler_route.gpx" ]; then
    cp "$PROJECT_ROOT/oetztaler_route.gpx" "$STAGING_APP/"
fi

# 4. Synchronisiere in Serious Python SPM Resources & Bundle-Verzeichnisse
TARGET_DIRS=()

if [ -d "$SPM_APP" ] && [ -w "$SPM_APP" ]; then
    TARGET_DIRS+=("$SPM_APP")
fi

if [ -d "$PUB_CACHE_SPM" ] && [ -w "$PUB_CACHE_SPM" ]; then
    REAL_SPM=$(cd "$SPM_APP" 2>/dev/null && pwd -P || echo "")
    REAL_PUB=$(cd "$PUB_CACHE_SPM" 2>/dev/null && pwd -P || echo "")
    if [ -z "$REAL_SPM" ] || [ "$REAL_SPM" != "$REAL_PUB" ]; then
        TARGET_DIRS+=("$PUB_CACHE_SPM")
    elif [ ${#TARGET_DIRS[@]} -eq 0 ]; then
        TARGET_DIRS+=("$PUB_CACHE_SPM")
    fi
fi

# Auch vorhandene iOS-Build-Bundles synchronisieren
for bundle_app in \
    "$PROJECT_ROOT/build/flutter/build/ios/Debug-iphonesimulator/power-planner.app/serious_python_darwin_serious_python_darwin.bundle/app" \
    "$PROJECT_ROOT/build/flutter/build/ios/iphonesimulator/power-planner.app/serious_python_darwin_serious_python_darwin.bundle/app" \
    "$PROJECT_ROOT/build/ios-simulator/power-planner.app/serious_python_darwin_serious_python_darwin.bundle/app" \
    "$PROJECT_ROOT/build/flutter/build/ios/Debug-iphonesimulator/serious_python_darwin_serious_python_darwin.bundle/app"; do
    if [ -d "$bundle_app" ] && [ -w "$bundle_app" ]; then
        TARGET_DIRS+=("$bundle_app")
    fi
done

for target in "${TARGET_DIRS[@]}"; do
    echo "🚀 Aktualisiere Python-Dateien in: $target"
    for f in "${PYTHON_FILES[@]}"; do
        base="${f%.*}"
        rm -f "$target/$base".* "$target/$base".pyc
        cp "$PROJECT_ROOT/$f" "$target/"
    done
    if [ -f "$PROJECT_ROOT/oetztaler_route.gpx" ]; then
        cp "$PROJECT_ROOT/oetztaler_route.gpx" "$target/"
    fi
done

# 5. Kompiliere frische Bytecode-Dateien (.pyc) mit exakt gleichem Python 3.14
if [ -x "$PROJECT_ROOT/pacing-env/bin/python" ]; then
    COMPILE_TARGETS=("$STAGING_APP")
    for t in "${TARGET_DIRS[@]}"; do
        COMPILE_TARGETS+=("$t")
    done
    "$PROJECT_ROOT/pacing-env/bin/python" -m compileall -b -q "${COMPILE_TARGETS[@]}"
fi

# 6. Cache-Stempel von Flet aktualisieren
if [ -f "$PROJECT_ROOT/build/.hash/package" ]; then
    rm -f "$PROJECT_ROOT/build/.hash/package"
fi

echo "✅ [PowerPlanner iOS Sync] Erfolgreich synchronisiert! Xcode baut jetzt den aktuellsten Code."
