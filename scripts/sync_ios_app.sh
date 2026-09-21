#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "🔄 [PowerPlanner iOS Sync] Starte Synchronisation von Python -> iOS..."

# 1. Dynamische Build-Nummer aus Git-Commits
BUILD_NUM=$(git -C "$PROJECT_ROOT" rev-list --count HEAD 2>/dev/null || echo "1")
CONFIG="$PROJECT_ROOT/build/flutter/ios/Flutter/Generated.xcconfig"
if [ -f "$CONFIG" ]; then
    sed -i '' "s/FLUTTER_BUILD_NUMBER=.*/FLUTTER_BUILD_NUMBER=$BUILD_NUM/" "$CONFIG"
    echo "📌 Build-Nummer gesetzt auf: $BUILD_NUM"
fi

# 2. Zielverzeichnisse
STAGING_APP="$PROJECT_ROOT/build/python-app"
SPM_APP="$PROJECT_ROOT/build/flutter/ios/Flutter/ephemeral/Packages/.packages/serious_python_darwin-4.7.0/Sources/serious_python_darwin/Resources/app"

mkdir -p "$STAGING_APP"

# 3. Synchronisiere Python-Dateien in Staging
echo "📂 Kopiere aktuelle Python-Dateien..."
cp "$PROJECT_ROOT/power_planner_flet.py" "$STAGING_APP/"
cp "$PROJECT_ROOT/pacing_optimizer.py" "$STAGING_APP/"
cp "$PROJECT_ROOT/main.py" "$STAGING_APP/"
if [ -f "$PROJECT_ROOT/oetztaler_route.gpx" ]; then
    cp "$PROJECT_ROOT/oetztaler_route.gpx" "$STAGING_APP/"
fi

# 4. Synchronisiere in Serious Python SPM Resources (wird direkt in Runner.app gepackt)
if [ -d "$SPM_APP" ]; then
    echo "🚀 Aktualisiere Serious Python SPM Resources/app..."
    # Alte .pyc entfernen
    rm -f "$SPM_APP"/*.pyc "$SPM_APP"/power_planner_flet.* "$SPM_APP"/pacing_optimizer.* "$SPM_APP"/main.*
    
    cp "$PROJECT_ROOT/power_planner_flet.py" "$SPM_APP/"
    cp "$PROJECT_ROOT/pacing_optimizer.py" "$SPM_APP/"
    cp "$PROJECT_ROOT/main.py" "$SPM_APP/"
    if [ -f "$PROJECT_ROOT/oetztaler_route.gpx" ]; then
        cp "$PROJECT_ROOT/oetztaler_route.gpx" "$SPM_APP/"
    fi

    # Kompiliere frische Bytecode-Dateien (.pyc) mit exakt gleichem Python 3.14
    if [ -x "$PROJECT_ROOT/pacing-env/bin/python" ]; then
        "$PROJECT_ROOT/pacing-env/bin/python" -m compileall -b -q "$SPM_APP" "$STAGING_APP"
    fi
fi

# 5. Cache-Stempel von Flet aktualisieren
if [ -f "$PROJECT_ROOT/build/.hash/package" ]; then
    rm -f "$PROJECT_ROOT/build/.hash/package"
fi

echo "✅ [PowerPlanner iOS Sync] Erfolgreich synchronisiert! Xcode baut jetzt den aktuellsten Code."
