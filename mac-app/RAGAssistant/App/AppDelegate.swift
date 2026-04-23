import AppKit
import UserNotifications

// MARK: - AppDelegate

final class AppDelegate: NSObject, NSApplicationDelegate {

    private var backendProcess: Process?

    func applicationDidFinishLaunching(_ notification: Notification) {
        UNUserNotificationCenter.current().requestAuthorization(
            options: [.alert, .sound]
        ) { _, _ in }

        LaunchAtLoginHelper.register()
        startBackendIfNeeded()
    }

    func applicationWillTerminate(_ notification: Notification) {
        backendProcess?.terminate()
    }

    // MARK: - Backend Launch

    private func startBackendIfNeeded() {
        checkBackendHealth { [weak self] alive in
            guard !alive else { return }
            DispatchQueue.main.async {
                self?.launchDockerCompose()
            }
        }
    }

    private func launchDockerCompose() {
        guard let projectPath = findProjectPath() else {
            NSLog("RAGAssistant: не удалось найти папку проекта")
            return
        }

        // Ищем docker в нескольких стандартных локациях вместо захардкоженного пути
        guard let dockerPath = findDockerExecutable() else {
            NSLog("RAGAssistant: docker не найден. Установи Docker Desktop.")
            // Показываем уведомление пользователю
            sendDockerNotFoundNotification()
            return
        }

        let process = Process()
        process.executableURL = URL(fileURLWithPath: dockerPath)
        process.arguments = [
            "compose",
            "-f", "\(projectPath)/docker-compose.yml",
            "-f", "\(projectPath)/docker-compose.dev.yml",
            "up", "--no-build", "-d",
        ]
        process.currentDirectoryURL = URL(fileURLWithPath: projectPath)

        // Захватываем вывод для логирования
        let pipe = Pipe()
        process.standardError = pipe

        do {
            try process.run()
            backendProcess = process
            NSLog("RAGAssistant: docker compose запущен (path: \(dockerPath))")
        } catch {
            NSLog("RAGAssistant: ошибка запуска docker compose: \(error)")
        }
    }

    // MARK: - Docker Discovery

    /// Ищет исполняемый файл docker в стандартных местах установки.
    /// Поддерживает: Docker Desktop (Intel + Apple Silicon), Homebrew, PATH.
    private func findDockerExecutable() -> String? {
        let candidates = [
            // Docker Desktop (Intel Mac)
            "/usr/local/bin/docker",
            // Docker Desktop (Apple Silicon через symlink)
            "/opt/homebrew/bin/docker",
            // Homebrew Intel
            "/usr/local/opt/docker/bin/docker",
            // Homebrew Apple Silicon
            "/opt/homebrew/opt/docker/bin/docker",
            // OrbStack (альтернатива Docker Desktop)
            "/opt/orbstack-bin/bin/docker",
            // Rancher Desktop
            "/home/\(NSUserName())/.rd/bin/docker",
            // Colima
            "/usr/local/bin/docker",
        ]

        for path in candidates {
            if FileManager.default.isExecutableFile(atPath: path) {
                return path
            }
        }

        // Последняя попытка — через PATH через shell
        return findViaShell("docker")
    }

    /// Ищет команду через /bin/zsh -l -c which <cmd>
    private func findViaShell(_ command: String) -> String? {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/bin/zsh")
        process.arguments = ["-l", "-c", "which \(command)"]
        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = Pipe()
        do {
            try process.run()
            process.waitUntilExit()
            let data = pipe.fileHandleForReading.readDataToEndOfFile()
            let path = String(data: data, encoding: .utf8)?
                .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            return path.isEmpty ? nil : path
        } catch {
            return nil
        }
    }

    // MARK: - Project Path Discovery

    private func findProjectPath() -> String? {
        let candidates = [
            Bundle.main.bundlePath
                .components(separatedBy: "/")
                .dropLast(3)
                .joined(separator: "/"),
            NSHomeDirectory() + "/Developer/rag-dev-assistant",
            NSHomeDirectory() + "/Documents/rag-dev-assistant",
            NSHomeDirectory() + "/Projects/rag-dev-assistant",
        ]
        return candidates.first {
            FileManager.default.fileExists(atPath: $0 + "/docker-compose.yml")
        }
    }

    // MARK: - Health Check

    private func checkBackendHealth(completion: @escaping (Bool) -> Void) {
        guard let url = URL(string: UserDefaults.standard.backendURL + "/health") else {
            completion(false)
            return
        }
        URLSession.shared.dataTask(with: url) { _, response, _ in
            let ok = (response as? HTTPURLResponse)?.statusCode == 200
            completion(ok)
        }.resume()
    }

    // MARK: - Notifications

    private func sendDockerNotFoundNotification() {
        let content = UNMutableNotificationContent()
        content.title = "RAG Dev Assistant"
        content.body = "Docker не найден. Установи Docker Desktop для запуска бэкенда."
        content.sound = .default
        UNUserNotificationCenter.current().add(
            UNNotificationRequest(identifier: "docker-not-found", content: content, trigger: nil)
        )
    }
}

// MARK: - Launch At Login

enum LaunchAtLoginHelper {
    static func register() {
        // macOS 13+: SMAppService.mainApp.register()
        // Реализуется при подписании приложения
    }
}
