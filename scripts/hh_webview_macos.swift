import Cocoa
import WebKit

final class AuthAppDelegate: NSObject, NSApplicationDelegate, WKNavigationDelegate, WKUIDelegate, WKScriptMessageHandler, NSWindowDelegate {
    let targetUrl: String
    let callbackUrl: String
    let clearSession: Bool
    var window: NSWindow!
    var container: NSView!
    var topBarHeight: CGFloat = 44
    var webView: WKWebView!
    var popupWebViews: [WKWebView] = []
    var urlLabel: NSTextField!
    var statusLabel: NSTextField!
    var completed = false

    let safariUserAgent = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Safari/605.1.15"

    init(targetUrl: String, callbackUrl: String, clearSession: Bool) {
        self.targetUrl = targetUrl
        self.callbackUrl = callbackUrl
        self.clearSession = clearSession
        super.init()
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        let screenRect = NSScreen.main?.visibleFrame ?? NSRect(x: 0, y: 0, width: 1200, height: 800)
        let width: CGFloat = min(1020, screenRect.width * 0.85)
        let height: CGFloat = min(780, screenRect.height * 0.85)
        let rect = NSRect(
            x: screenRect.origin.x + (screenRect.width - width) / 2,
            y: screenRect.origin.y + (screenRect.height - height) / 2,
            width: width,
            height: height
        )

        window = NSWindow(
            contentRect: rect,
            styleMask: [.titled, .closable, .resizable, .miniaturizable],
            backing: .buffered,
            defer: false
        )
        window.title = "Hammerhead / SRAM Anmeldung — Power-Planner"
        window.delegate = self
        window.appearance = NSAppearance(named: .darkAqua)
        window.backgroundColor = NSColor(calibratedRed: 0.08, green: 0.10, blue: 0.13, alpha: 1.0)

        container = NSView(frame: NSRect(x: 0, y: 0, width: width, height: height))
        container.autoresizingMask = [.width, .height]

        let topBar = NSView(frame: NSRect(x: 0, y: height - topBarHeight, width: width, height: topBarHeight))
        topBar.autoresizingMask = [.width, .minYMargin]
        topBar.wantsLayer = true
        topBar.layer?.backgroundColor = NSColor(calibratedRed: 0.11, green: 0.14, blue: 0.18, alpha: 1.0).cgColor

        urlLabel = NSTextField(labelWithString: "🔒 \(targetUrl)")
        urlLabel.frame = NSRect(x: 16, y: 12, width: width - 320, height: 20)
        urlLabel.autoresizingMask = [.width]
        urlLabel.textColor = NSColor(calibratedWhite: 0.85, alpha: 1.0)
        urlLabel.font = NSFont.monospacedSystemFont(ofSize: 12, weight: .regular)
        urlLabel.lineBreakMode = .byTruncatingTail
        topBar.addSubview(urlLabel)

        statusLabel = NSTextField(labelWithString: "Bitte bei Hammerhead / SRAM anmelden…")
        statusLabel.frame = NSRect(x: width - 295, y: 12, width: 280, height: 20)
        statusLabel.autoresizingMask = [.minXMargin]
        statusLabel.alignment = .right
        statusLabel.textColor = NSColor.systemYellow
        statusLabel.font = NSFont.systemFont(ofSize: 12, weight: .medium)
        topBar.addSubview(statusLabel)

        let config = WKWebViewConfiguration()
        config.websiteDataStore = WKWebsiteDataStore.default()
        config.preferences.javaScriptCanOpenWindowsAutomatically = true

        let contentController = WKUserContentController()
        contentController.add(self, name: "powerPlannerAuth")

        // Wichtig: Skript greift NUR auf dashboard.hammerhead.io nach dem Login,
        // niemals auf sramid-auth.sram.com, damit Auth0/SRAM-Handshakes ungestört bleiben.
        let js = """
        (function() {
            if (window.location.hostname !== 'dashboard.hammerhead.io') return;
            if (window.__ppAuthInstalled) return;
            window.__ppAuthInstalled = true;

            function parseJwt(tok) {
                if (!tok || typeof tok !== 'string') return null;
                var clean = tok.trim();
                if (clean.toLowerCase().indexOf('bearer ') === 0) {
                    clean = clean.slice(7).trim();
                }
                var parts = clean.split('.');
                if (parts.length !== 3) return null;
                try {
                    var b64 = parts[1].replace(/-/g, '+').replace(/_/g, '/');
                    while (b64.length % 4 !== 0) b64 += '=';
                    var raw = atob(b64);
                    var payload = JSON.parse(raw);
                    var uid = payload.sub || payload.user_id || payload.id;
                    if (!uid) return null;
                    if (payload.exp && (payload.exp * 1000) < Date.now()) return null;
                    var email = payload.email || payload.preferred_username || payload.name || '';
                    return { token: clean, userId: String(uid), email: String(email) };
                } catch (e) {
                    return null;
                }
            }

            function reportToken(rawToken, extraUserId, extraEmail) {
                if (window.__ppTokenReported) return;
                var parsed = parseJwt(rawToken);
                if (!parsed) return;
                window.__ppTokenReported = true;
                try {
                    window.webkit.messageHandlers.powerPlannerAuth.postMessage({
                        token: parsed.token,
                        userId: extraUserId || parsed.userId || '',
                        email: extraEmail || parsed.email || ''
                    });
                } catch (e) {}
            }

            var origSetHeader = XMLHttpRequest.prototype.setRequestHeader;
            XMLHttpRequest.prototype.setRequestHeader = function(name, value) {
                try {
                    if (name && name.toLowerCase() === 'authorization' &&
                        value && value.toLowerCase().indexOf('bearer ') === 0) {
                        reportToken(value);
                    }
                } catch (e) {}
                return origSetHeader.apply(this, arguments);
            };

            var origFetch = window.fetch;
            if (origFetch) {
                window.fetch = function(input, init) {
                    try {
                        var hdrs = (init && init.headers) || (input && input.headers);
                        if (hdrs) {
                            var authVal = null;
                            if (typeof hdrs.get === 'function') {
                                authVal = hdrs.get('Authorization') || hdrs.get('authorization');
                            } else if (typeof hdrs === 'object') {
                                authVal = hdrs['Authorization'] || hdrs['authorization'];
                            }
                            if (authVal && authVal.toLowerCase().indexOf('bearer ') === 0) {
                                reportToken(authVal);
                            }
                        }
                    } catch (e) {}
                    return origFetch.apply(this, arguments);
                };
            }

            var jwtRegex = /eyJ[A-Za-z0-9_-]{10,}\\.eyJ[A-Za-z0-9_-]{10,}\\.[A-Za-z0-9_-]{10,}/g;
            function scanStorage() {
                if (window.__ppTokenReported) return;
                if (window.location.hostname !== 'dashboard.hammerhead.io') return;
                var path = window.location.pathname || '';
                if (path.indexOf('/login') === 0 || path.indexOf('/auth') === 0) return;

                var stores = [window.localStorage, window.sessionStorage];
                for (var s = 0; s < stores.length; s++) {
                    var st = stores[s];
                    if (!st) continue;
                    try {
                        for (var i = 0; i < st.length; i++) {
                            var k = st.key(i);
                            var v = st.getItem(k);
                            if (!v) continue;
                            var matches = v.match(jwtRegex);
                            if (matches) {
                                for (var m = 0; m < matches.length; m++) {
                                    if (parseJwt(matches[m])) {
                                        reportToken(matches[m]);
                                        return;
                                    }
                                }
                            }
                        }
                    } catch (e) {}
                }
                try {
                    var cMatches = (document.cookie || '').match(jwtRegex);
                    if (cMatches) {
                        for (var c = 0; c < cMatches.length; c++) {
                            if (parseJwt(cMatches[c])) {
                                reportToken(cMatches[c]);
                                return;
                            }
                        }
                    }
                } catch (e) {}
            }
            setInterval(scanStorage, 500);
        })();
        """

        let script = WKUserScript(source: js, injectionTime: .atDocumentEnd, forMainFrameOnly: true)
        contentController.addUserScript(script)
        config.userContentController = contentController

        webView = WKWebView(frame: NSRect(x: 0, y: 0, width: width, height: height - topBarHeight), configuration: config)
        webView.autoresizingMask = [.width, .height]
        webView.navigationDelegate = self
        webView.uiDelegate = self
        webView.customUserAgent = safariUserAgent

        container.addSubview(topBar)
        container.addSubview(webView)
        window.contentView = container
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)

        let loadTarget = {
            if let url = URL(string: self.targetUrl) {
                self.webView.load(URLRequest(url: url))
            }
        }

        if clearSession {
            let dataStore = WKWebsiteDataStore.default()
            let types = WKWebsiteDataStore.allWebsiteDataTypes()
            dataStore.fetchDataRecords(ofTypes: types) { records in
                dataStore.removeData(ofTypes: types, for: records) {
                    DispatchQueue.main.async {
                        loadTarget()
                    }
                }
            }
        } else {
            loadTarget()
        }
    }

    // Unterstützt OAuth-Popups (window.open / target="_blank") von SRAM / Auth0
    func webView(
        _ webView: WKWebView,
        createWebViewWith configuration: WKWebViewConfiguration,
        for navigationAction: WKNavigationAction,
        windowFeatures: WKWindowFeatures
    ) -> WKWebView? {
        configuration.preferences.javaScriptCanOpenWindowsAutomatically = true
        let popup = WKWebView(frame: self.webView.frame, configuration: configuration)
        popup.autoresizingMask = [.width, .height]
        popup.navigationDelegate = self
        popup.uiDelegate = self
        popup.customUserAgent = safariUserAgent
        container.addSubview(popup)
        popupWebViews.append(popup)
        return popup
    }

    func webViewDidClose(_ webView: WKWebView) {
        if let idx = popupWebViews.firstIndex(of: webView) {
            popupWebViews.remove(at: idx)
            webView.removeFromSuperview()
        }
    }

    func webView(_ webView: WKWebView, didCommit navigation: WKNavigation!) {
        if let u = webView.url?.absoluteString {
            urlLabel.stringValue = "🔒 \(u)"
        }
    }

    func interceptOAuthCallbackIfPresent(_ url: URL?) -> Bool {
        guard let url = url else { return false }
        let host = (url.host ?? "").lowercased()
        let path = url.path
        if host == "dashboard.hammerhead.io" && path.hasPrefix("/accounts/callback") {
            if let comps = URLComponents(url: url, resolvingAgainstBaseURL: false),
               let items = comps.queryItems,
               let codeItem = items.first(where: { $0.name == "code" }),
               let code = codeItem.value, !code.isEmpty {
                if !completed {
                    completed = true
                    reportOAuthCode(code)
                }
                return true
            }
        }
        return false
    }

    func webView(
        _ webView: WKWebView,
        decidePolicyFor navigationAction: WKNavigationAction,
        decisionHandler: @escaping (WKNavigationActionPolicy) -> Void
    ) {
        if interceptOAuthCallbackIfPresent(navigationAction.request.url) {
            decisionHandler(.cancel)
            return
        }
        decisionHandler(.allow)
    }

    func webView(
        _ webView: WKWebView,
        decidePolicyFor navigationResponse: WKNavigationResponse,
        decisionHandler: @escaping (WKNavigationResponsePolicy) -> Void
    ) {
        if interceptOAuthCallbackIfPresent(navigationResponse.response.url) {
            decisionHandler(.cancel)
            return
        }
        decisionHandler(.allow)
    }

    func reportOAuthCode(_ code: String) {
        statusLabel.stringValue = "🔄 Verbinde mit Hammerhead Cloud…"
        statusLabel.textColor = NSColor.systemYellow

        var comps = URLComponents(string: callbackUrl)
        comps?.queryItems = [
            URLQueryItem(name: "code", value: code)
        ]

        if let finalUrl = comps?.url {
            let task = URLSession.shared.dataTask(with: finalUrl) { data, response, _ in
                let statusCode = (response as? HTTPURLResponse)?.statusCode ?? 0
                DispatchQueue.main.async {
                    if statusCode == 200 {
                        self.statusLabel.stringValue = "✅ Erfolgreich angemeldet!"
                        self.statusLabel.textColor = NSColor.systemGreen
                        if let data = data, let html = String(data: data, encoding: .utf8) {
                            self.webView.loadHTMLString(html, baseURL: nil)
                        }
                        DispatchQueue.main.asyncAfter(deadline: .now() + 0.6) {
                            NSApp.terminate(nil)
                        }
                    } else {
                        self.completed = false
                        self.statusLabel.stringValue = "⚠️ Verbindung fehlgeschlagen (HTTP \(statusCode))"
                        self.statusLabel.textColor = NSColor.systemRed
                        if let data = data, let html = String(data: data, encoding: .utf8) {
                            self.webView.loadHTMLString(html, baseURL: nil)
                        }
                    }
                }
            }
            task.resume()
        } else {
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.4) {
                NSApp.terminate(nil)
            }
        }
    }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        if completed { return }
        guard let body = message.body as? [String: Any],
              let token = body["token"] as? String,
              !token.isEmpty else { return }

        completed = true
        let userId = (body["userId"] as? String) ?? ""
        let email = (body["email"] as? String) ?? "Hammerhead SRAM SSO"

        statusLabel.stringValue = "✅ Erfolgreich angemeldet!"
        statusLabel.textColor = NSColor.systemGreen

        var comps = URLComponents(string: callbackUrl)
        comps?.queryItems = [
            URLQueryItem(name: "token", value: token),
            URLQueryItem(name: "user_id", value: userId),
            URLQueryItem(name: "email", value: email)
        ]

        if let finalUrl = comps?.url {
            let task = URLSession.shared.dataTask(with: finalUrl) { _, _, _ in
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.4) {
                    NSApp.terminate(nil)
                }
            }
            task.resume()
        } else {
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.4) {
                NSApp.terminate(nil)
            }
        }
    }

    func windowWillClose(_ notification: Notification) {
        NSApp.terminate(nil)
    }
}

let args = CommandLine.arguments
let targetUrl = args.count > 1 ? args[1] : "https://dashboard.hammerhead.io"
let callbackUrl = args.count > 2 ? args[2] : "http://127.0.0.1:8080/callback"
let clearSession = args.count > 3 && args[3] == "--clear"

let app = NSApplication.shared
app.setActivationPolicy(.regular)
let delegate = AuthAppDelegate(targetUrl: targetUrl, callbackUrl: callbackUrl, clearSession: clearSession)
app.delegate = delegate
app.run()
