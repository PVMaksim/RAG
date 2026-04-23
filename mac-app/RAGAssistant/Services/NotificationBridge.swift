import UserNotifications
import Foundation

// MARK: - NotificationBridge

/// Принимает события из JavaScript через WKScriptMessageHandler
/// и отправляет нативные macOS уведомления.
///
/// Web UI вызывает:
///   window.__ragBridge.notify("Сканирование завершено", "my_bot: 118 файлов")
enum NotificationBridge {

    static func sendScanComplete(project: String, fileCount: Int) {
        send(
            title: "✅ Сканирование завершено",
            body: "\(project): \(fileCount) файлов проиндексировано"
        )
    }

    static func sendGraphComplete(project: String, nodes: Int) {
        send(
            title: "🕸 Граф знаний построен",
            body: "\(project): \(nodes) узлов"
        )
    }

    static func sendError(message: String) {
        send(title: "❌ RAG Dev Assistant", body: message)
    }

    // MARK: - Core

    static func send(title: String, body: String) {
        UNUserNotificationCenter.current().getNotificationSettings { settings in
            guard settings.authorizationStatus == .authorized else { return }

            let content = UNMutableNotificationContent()
            content.title = title
            content.body = body
            content.sound = .default

            let request = UNNotificationRequest(
                identifier: UUID().uuidString,
                content: content,
                trigger: nil   // Немедленно
            )

            UNUserNotificationCenter.current().add(request)
        }
    }
}
