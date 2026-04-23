import SwiftUI
import WebKit

// MARK: - MenuBarView

/// Главное popup-окно при клике на иконку в menu bar.
/// Содержит WKWebView → Next.js Web UI.
struct MenuBarView: View {

    @EnvironmentObject var appState: AppState
    @State private var currentPath: String = "/search"
    @State private var webViewRef: WKWebView?
    @State private var isLoading: Bool = true

    var body: some View {
        VStack(spacing: 0) {

            // ── Таб-бар ────────────────────────────────────────────────────
            HStack(spacing: 0) {
                TabButton(icon: "magnifyingglass", label: "Поиск",    path: "/search",   current: $currentPath)
                TabButton(icon: "folder",          label: "Проекты",  path: "/projects", current: $currentPath)
                TabButton(icon: "point.3.connected.trianglepath.dotted", label: "Граф", path: "/graph", current: $currentPath)

                Spacer()

                // Индикатор бэкенда
                Circle()
                    .fill(appState.backendOnline ? Color.green : Color.secondary)
                    .frame(width: 7, height: 7)
                    .help(appState.backendOnline ? "Бэкенд онлайн" : "Бэкенд недоступен")
                    .padding(.trailing, 12)
            }
            .frame(height: 38)
            .background(.bar)
            .overlay(alignment: .bottom) {
                Divider()
            }

            // ── Web View ───────────────────────────────────────────────────
            ZStack {
                WebContentView(
                    url: fullURL(for: currentPath),
                    onNavigate: { path in currentPath = path },
                    isLoading: $isLoading,
                    webViewRef: $webViewRef
                )

                // Спиннер пока загружается
                if isLoading {
                    VStack(spacing: 12) {
                        ProgressView()
                            .scaleEffect(0.8)
                        Text(appState.backendOnline ? "Загружаю..." : "Запускаю бэкенд...")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                    .background(.regularMaterial)
                }
            }
        }
        .frame(width: 900, height: 640)
        .onChange(of: currentPath) { path in
            navigateTo(path)
        }
        .onChange(of: appState.backendURL) { _ in
            reloadWebView()
        }
    }

    // MARK: - Navigation

    private func fullURL(for path: String) -> URL {
        URL(string: appState.backendURL + path)
        ?? URL(string: "http://localhost:8080" + path)!
    }

    private func navigateTo(_ path: String) {
        guard let webView = webViewRef else { return }
        let url = fullURL(for: path)
        if webView.url?.path != path {
            webView.load(URLRequest(url: url))
        }
    }

    private func reloadWebView() {
        webViewRef?.load(URLRequest(url: fullURL(for: currentPath)))
    }
}

// MARK: - TabButton

struct TabButton: View {
    let icon: String
    let label: String
    let path: String
    @Binding var current: String

    private var isActive: Bool { current.hasPrefix(path) }

    var body: some View {
        Button {
            current = path
        } label: {
            VStack(spacing: 2) {
                Image(systemName: icon)
                    .font(.system(size: 13))
                Text(label)
                    .font(.system(size: 10))
            }
            .foregroundStyle(isActive ? .blue : .secondary)
            .frame(width: 64, height: 36)
            .background(isActive ? Color.blue.opacity(0.08) : .clear)
        }
        .buttonStyle(.plain)
    }
}

// MARK: - WebContentView

/// NSViewRepresentable обёртка над WKWebView.
struct WebContentView: NSViewRepresentable {

    let url: URL
    var onNavigate: (String) -> Void
    @Binding var isLoading: Bool
    @Binding var webViewRef: WKWebView?

    func makeCoordinator() -> Coordinator {
        Coordinator(self)
    }

    func makeNSView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()

        // JavaScript bridge: Web UI может слать уведомления macOS
        let controller = config.userContentController
        controller.add(context.coordinator, name: "notify")
        controller.add(context.coordinator, name: "navigateTo")

        // Inject скрипт — синхронизируем навигацию Web UI с таб-баром
        let script = WKUserScript(
            source: """
            window.__ragBridge = {
              notify: (title, body) => window.webkit.messageHandlers.notify.postMessage({title, body}),
              navigateTo: (path) => window.webkit.messageHandlers.navigateTo.postMessage(path)
            };
            // Перехватываем popstate и pushState
            const orig = history.pushState.bind(history);
            history.pushState = function(state, title, url) {
              orig(state, title, url);
              window.webkit.messageHandlers.navigateTo.postMessage(url);
            };
            """,
            injectionTime: .atDocumentStart,
            forMainFrameOnly: true
        )
        controller.addUserScript(script)

        let webView = WKWebView(frame: .zero, configuration: config)
        webView.navigationDelegate = context.coordinator

        // Прозрачный фон для поддержки dark mode
        webView.setValue(false, forKey: "drawsBackground")

        // Загружаем начальный URL
        webView.load(URLRequest(url: url))

        DispatchQueue.main.async {
            self.webViewRef = webView
        }

        return webView
    }

    func updateNSView(_ webView: WKWebView, context: Context) {
        // Навигация управляется через webViewRef, не через updateNSView
    }

    // MARK: - Coordinator

    final class Coordinator: NSObject, WKNavigationDelegate, WKScriptMessageHandler {
        var parent: WebContentView

        init(_ parent: WebContentView) { self.parent = parent }

        // Уведомления из JavaScript
        func userContentController(
            _ controller: WKUserContentController,
            didReceive message: WKScriptMessage
        ) {
            switch message.name {
            case "notify":
                guard let body = message.body as? [String: String] else { return }
                sendMacOSNotification(
                    title: body["title"] ?? "RAG Assistant",
                    body: body["body"] ?? ""
                )
            case "navigateTo":
                guard let path = message.body as? String else { return }
                DispatchQueue.main.async {
                    self.parent.onNavigate(path)
                }
            default: break
            }
        }

        // Loading state
        func webView(_ webView: WKWebView, didStartProvisionalNavigation navigation: WKNavigation!) {
            DispatchQueue.main.async { self.parent.isLoading = true }
        }

        func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
            DispatchQueue.main.async { self.parent.isLoading = false }
        }

        func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
            DispatchQueue.main.async { self.parent.isLoading = false }
        }

        // Разрешаем навигацию внутри нашего домена
        func webView(
            _ webView: WKWebView,
            decidePolicyFor action: WKNavigationAction,
            decisionHandler: @escaping (WKNavigationActionPolicy) -> Void
        ) {
            guard let url = action.request.url else {
                decisionHandler(.allow)
                return
            }
            // Внешние ссылки открываем в браузере
            if url.host != URL(string: self.parent.url.absoluteString)?.host,
               action.navigationType == .linkActivated {
                NSWorkspace.shared.open(url)
                decisionHandler(.cancel)
            } else {
                decisionHandler(.allow)
            }
        }

        // MARK: - macOS Notifications

        private func sendMacOSNotification(title: String, body: String) {
            let content = UNMutableNotificationContent()
            content.title = title
            content.body = body
            content.sound = .default
            let request = UNNotificationRequest(
                identifier: UUID().uuidString,
                content: content,
                trigger: nil
            )
            UNUserNotificationCenter.current().add(request)
        }
    }
}
