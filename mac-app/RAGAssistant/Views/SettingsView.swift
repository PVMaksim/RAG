import SwiftUI

// MARK: - SettingsView

/// Нативное окно настроек (⌘, / через меню).
struct SettingsView: View {

    @EnvironmentObject var appState: AppState
    @State private var testResult: String? = nil
    @State private var testing = false

    var body: some View {
        TabView {
            GeneralTab()
                .tabItem { Label("Основное", systemImage: "gearshape") }
                .environmentObject(appState)

            MCPTab()
                .tabItem { Label("MCP", systemImage: "puzzlepiece") }
                .environmentObject(appState)

            AboutTab()
                .tabItem { Label("О приложении", systemImage: "info.circle") }
        }
        .frame(width: 480, height: 320)
    }
}

// MARK: - General Tab

struct GeneralTab: View {

    @EnvironmentObject var appState: AppState
    @State private var urlDraft: String = ""
    @State private var testStatus: TestStatus = .idle
    @AppStorage("launchAtLogin") private var launchAtLogin = false

    enum TestStatus { case idle, testing, ok, fail }

    var body: some View {
        Form {
            Section("Бэкенд") {
                HStack {
                    TextField("URL бэкенда", text: $urlDraft)
                        .textFieldStyle(.roundedBorder)
                        .onAppear { urlDraft = appState.backendURL }

                    Button("Тест") {
                        testConnection()
                    }
                    .disabled(testStatus == .testing)
                }

                HStack(spacing: 6) {
                    Circle()
                        .fill(statusColor)
                        .frame(width: 7, height: 7)
                    Text(statusText)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }

                Button("Сохранить") {
                    appState.backendURL = urlDraft
                    appState.checkHealth()
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.small)
            }

            Section("Запуск") {
                Toggle("Запускать при входе в macOS", isOn: $launchAtLogin)
                    .onChange(of: launchAtLogin) { enabled in
                        if enabled { LaunchAtLoginHelper.register() }
                    }

                HStack {
                    Text("Глобальный хоткей")
                    Spacer()
                    Text("⌥Space")
                        .font(.system(.caption, design: .monospaced))
                        .padding(.horizontal, 8)
                        .padding(.vertical, 3)
                        .background(.quaternary)
                        .clipShape(RoundedRectangle(cornerRadius: 4))
                }
            }

            Section("API Ключ") {
                Text("Задаётся через переменную окружения ANTHROPIC_API_KEY в файле .env")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .formStyle(.grouped)
        .padding()
    }

    private var statusColor: Color {
        switch testStatus {
        case .idle:    return appState.backendOnline ? .green : .secondary
        case .testing: return .yellow
        case .ok:      return .green
        case .fail:    return .red
        }
    }

    private var statusText: String {
        switch testStatus {
        case .idle:    return appState.backendOnline ? "Онлайн" : "Недоступен"
        case .testing: return "Проверяю..."
        case .ok:      return "Подключено ✓"
        case .fail:    return "Не удалось подключиться"
        }
    }

    private func testConnection() {
        testStatus = .testing
        guard let url = URL(string: urlDraft + "/health") else {
            testStatus = .fail
            return
        }
        URLSession.shared.dataTask(with: url) { _, response, _ in
            DispatchQueue.main.async {
                testStatus = (response as? HTTPURLResponse)?.statusCode == 200 ? .ok : .fail
            }
        }.resume()
    }
}

// MARK: - MCP Tab

struct MCPTab: View {

    @EnvironmentObject var appState: AppState

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {

                Text("Подключи AI-ассистентов к своим проектам")
                    .font(.headline)

                Text("MCP-сервер работает на localhost:27183 и позволяет Claude Desktop, Cursor и Windsurf искать по коду без загрузки файлов в контекст.")
                    .font(.caption)
                    .foregroundStyle(.secondary)

                CodeBlock(title: "Claude Desktop", code: """
{
  "mcpServers": {
    "rag": {
      "command": "npx",
      "args": ["mcp-remote",
               "http://localhost:27183/mcp/sse"]
    }
  }
}
""")

                CodeBlock(title: "Cursor / Windsurf (.cursor/mcp.json)", code: """
{
  "mcpServers": {
    "rag": {
      "url": "http://localhost:27183/mcp/sse"
    }
  }
}
""")
                Button("Открыть конфиг Claude Desktop") {
                    let path = NSHomeDirectory() + "/Library/Application Support/Claude/claude_desktop_config.json"
                    NSWorkspace.shared.selectFile(path, inFileViewerRootedAtPath: "")
                }
                .controlSize(.small)
            }
            .padding()
        }
    }
}

// MARK: - About Tab

struct AboutTab: View {
    var body: some View {
        VStack(spacing: 12) {
            Image(systemName: "magnifyingglass.circle.fill")
                .font(.system(size: 48))
                .foregroundStyle(.blue)

            Text("RAG Dev Assistant")
                .font(.title2.bold())

            Text("Версия 1.0.0")
                .foregroundStyle(.secondary)

            Divider()

            Text("Семантический поиск по IT-проектам\nс Knowledge Graph и MCP-сервером")
                .multilineTextAlignment(.center)
                .font(.caption)
                .foregroundStyle(.secondary)

            Link("github.com/PVMaksim/rag-dev-assistant",
                 destination: URL(string: "https://github.com/PVMaksim/rag-dev-assistant")!)
                .font(.caption)
        }
        .padding(24)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

// MARK: - CodeBlock

struct CodeBlock: View {
    let title: String
    let code: String
    @State private var copied = false

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title)
                .font(.caption.bold())
                .foregroundStyle(.secondary)

            ZStack(alignment: .topTrailing) {
                Text(code)
                    .font(.system(.caption2, design: .monospaced))
                    .padding(10)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(.quaternary)
                    .clipShape(RoundedRectangle(cornerRadius: 6))

                Button(copied ? "✓" : "Копировать") {
                    NSPasteboard.general.clearContents()
                    NSPasteboard.general.setString(code, forType: .string)
                    copied = true
                    DispatchQueue.main.asyncAfter(deadline: .now() + 2) { copied = false }
                }
                .controlSize(.mini)
                .padding(6)
            }
        }
    }
}
