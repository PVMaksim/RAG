import SwiftUI

// MARK: - OnboardingView

/// Окно первого запуска — появляется один раз, пока бэкенд не настроен.
/// Проводит пользователя через: URL бэкенда → проверка соединения → готово.
struct OnboardingView: View {

    @EnvironmentObject var appState: AppState
    @State private var step: Step = .welcome
    @State private var urlDraft: String = "http://localhost:8080"
    @State private var testStatus: TestStatus = .idle
    @State private var errorMessage: String? = nil

    enum Step { case welcome, configure, done }
    enum TestStatus { case idle, testing, ok, fail }

    var body: some View {
        VStack(spacing: 0) {
            // ── Прогресс ───────────────────────────────────────────────────
            HStack(spacing: 8) {
                ForEach(0..<3) { i in
                    let stepIndex = stepIndex(for: step)
                    Capsule()
                        .fill(i <= stepIndex ? Color.blue : Color.secondary.opacity(0.3))
                        .frame(height: 3)
                }
            }
            .padding(.horizontal, 24)
            .padding(.top, 20)

            // ── Контент шага ───────────────────────────────────────────────
            switch step {
            case .welcome:    WelcomeStep(onNext: { step = .configure })
            case .configure:  ConfigureStep(
                urlDraft: $urlDraft,
                testStatus: $testStatus,
                errorMessage: $errorMessage,
                onTest: testConnection,
                onFinish: { finishOnboarding() }
            )
            case .done:       DoneStep(onClose: { finishOnboarding() })
            }
        }
        .frame(width: 420, height: 380)
    }

    // MARK: - Actions

    private func testConnection() {
        testStatus = .testing
        errorMessage = nil
        guard let url = URL(string: urlDraft + "/health") else {
            testStatus = .fail
            errorMessage = "Неверный URL"
            return
        }
        URLSession.shared.dataTask(with: url) { data, response, error in
            DispatchQueue.main.async {
                if let http = response as? HTTPURLResponse, http.statusCode == 200 {
                    self.testStatus = .ok
                    self.appState.backendURL = self.urlDraft
                    // Небольшая пауза перед переходом к done
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.8) {
                        self.step = .done
                    }
                } else {
                    self.testStatus = .fail
                    self.errorMessage = error?.localizedDescription ?? "Сервер не отвечает"
                }
            }
        }.resume()
    }

    private func finishOnboarding() {
        UserDefaults.standard.set(true, forKey: "onboardingCompleted")
        appState.backendURL = urlDraft
        appState.checkHealth()
    }

    private func stepIndex(for step: Step) -> Int {
        switch step { case .welcome: return 0; case .configure: return 1; case .done: return 2 }
    }
}

// MARK: - Welcome Step

private struct WelcomeStep: View {
    let onNext: () -> Void

    var body: some View {
        VStack(spacing: 20) {
            Spacer()
            Image(systemName: "magnifyingglass.circle.fill")
                .font(.system(size: 56))
                .foregroundStyle(.blue)

            VStack(spacing: 8) {
                Text("RAG Dev Assistant")
                    .font(.title2.bold())
                Text("Семантический поиск по IT-проектам\nс Knowledge Graph и MCP-сервером")
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
            }

            VStack(alignment: .leading, spacing: 10) {
                FeatureRow(icon: "magnifyingglass", text: "Поиск по коду за секунды")
                FeatureRow(icon: "point.3.connected.trianglepath.dotted", text: "Knowledge Graph зависимостей")
                FeatureRow(icon: "puzzlepiece", text: "MCP-сервер для Claude и Cursor")
            }
            .padding(.horizontal, 32)

            Spacer()

            Button("Начать настройку →") { onNext() }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
                .padding(.bottom, 24)
        }
        .padding()
    }
}

// MARK: - Configure Step

private struct ConfigureStep: View {
    @Binding var urlDraft: String
    @Binding var testStatus: OnboardingView.TestStatus
    @Binding var errorMessage: String?
    let onTest: () -> Void
    let onFinish: () -> Void

    var body: some View {
        VStack(spacing: 20) {
            Spacer()

            VStack(spacing: 6) {
                Image(systemName: "server.rack")
                    .font(.system(size: 36))
                    .foregroundStyle(.blue)
                Text("Подключение к бэкенду")
                    .font(.title3.bold())
                Text("Укажи URL где запущен Docker бэкенд")
                    .font(.callout)
                    .foregroundStyle(.secondary)
            }

            VStack(alignment: .leading, spacing: 8) {
                Text("URL бэкенда")
                    .font(.caption)
                    .foregroundStyle(.secondary)

                HStack {
                    TextField("http://localhost:8080", text: $urlDraft)
                        .textFieldStyle(.roundedBorder)
                        .onSubmit { onTest() }

                    Button(testStatus == .testing ? "..." : "Проверить") { onTest() }
                        .disabled(testStatus == .testing)
                }

                Group {
                    switch testStatus {
                    case .idle:    EmptyView()
                    case .testing: Label("Проверяю...", systemImage: "arrow.clockwise")
                            .foregroundStyle(.secondary)
                    case .ok:      Label("Подключено!", systemImage: "checkmark.circle.fill")
                            .foregroundStyle(.green)
                    case .fail:    Label(errorMessage ?? "Ошибка", systemImage: "xmark.circle.fill")
                            .foregroundStyle(.red)
                    }
                }
                .font(.caption)
            }
            .padding(.horizontal, 32)

            // Инструкция если не запущен
            if testStatus == .fail {
                VStack(alignment: .leading, spacing: 4) {
                    Text("Запусти бэкенд:")
                        .font(.caption.bold())
                    Text("cd rag-dev-assistant\n./scripts/setup.sh")
                        .font(.system(.caption, design: .monospaced))
                        .padding(8)
                        .background(.quaternary)
                        .clipShape(RoundedRectangle(cornerRadius: 6))
                }
                .padding(.horizontal, 32)
            }

            Spacer()

            HStack {
                Button("Пропустить") { onFinish() }
                    .foregroundStyle(.secondary)
                Spacer()
            }
            .padding(.horizontal, 32)
            .padding(.bottom, 24)
        }
        .padding()
    }
}

// MARK: - Done Step

private struct DoneStep: View {
    let onClose: () -> Void

    var body: some View {
        VStack(spacing: 20) {
            Spacer()

            Image(systemName: "checkmark.circle.fill")
                .font(.system(size: 56))
                .foregroundStyle(.green)

            VStack(spacing: 8) {
                Text("Готово!")
                    .font(.title2.bold())
                Text("RAG Dev Assistant настроен.\nИконка появится в строке меню.")
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
            }

            VStack(alignment: .leading, spacing: 10) {
                FeatureRow(icon: "command", text: "Хоткей ⌥Space открывает поиск")
                FeatureRow(icon: "folder", text: "Добавь проект в разделе «Проекты»")
                FeatureRow(icon: "puzzlepiece", text: "Подключи Claude Desktop через MCP")
            }
            .padding(.horizontal, 32)

            Spacer()

            Button("Начать работу") { onClose() }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
                .padding(.bottom, 24)
        }
        .padding()
    }
}

// MARK: - Helper Views

private struct FeatureRow: View {
    let icon: String
    let text: String

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: icon)
                .foregroundStyle(.blue)
                .frame(width: 20)
            Text(text)
                .font(.callout)
        }
    }
}

// MARK: - AppState extension для onboarding

extension AppState {
    var isOnboardingNeeded: Bool {
        !UserDefaults.standard.bool(forKey: "onboardingCompleted")
    }
}
