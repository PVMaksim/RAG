import Foundation
import Security

// MARK: - KeychainService

/// Безопасное хранение чувствительных данных в macOS Keychain.
/// API ключ никогда не хранится в UserDefaults или файлах.
enum KeychainService {

    private static let service = "com.pvmaksim.RAGAssistant"

    // MARK: - Public API

    static func save(_ value: String, forKey key: String) throws {
        guard let data = value.data(using: .utf8) else {
            throw KeychainError.encodingFailed
        }

        let query: [CFString: Any] = [
            kSecClass:       kSecClassGenericPassword,
            kSecAttrService: service,
            kSecAttrAccount: key,
        ]

        // Удаляем старое значение
        SecItemDelete(query as CFDictionary)

        // Сохраняем новое
        var attrs = query
        attrs[kSecValueData] = data
        let status = SecItemAdd(attrs as CFDictionary, nil)

        guard status == errSecSuccess else {
            throw KeychainError.saveFailed(status)
        }
    }

    static func load(forKey key: String) throws -> String {
        let query: [CFString: Any] = [
            kSecClass:           kSecClassGenericPassword,
            kSecAttrService:     service,
            kSecAttrAccount:     key,
            kSecReturnData:      true,
            kSecMatchLimit:      kSecMatchLimitOne,
        ]

        var result: AnyObject?
        let status = SecItemCopyMatching(query as CFDictionary, &result)

        guard status == errSecSuccess,
              let data = result as? Data,
              let string = String(data: data, encoding: .utf8)
        else {
            throw KeychainError.loadFailed(status)
        }

        return string
    }

    static func delete(forKey key: String) {
        let query: [CFString: Any] = [
            kSecClass:       kSecClassGenericPassword,
            kSecAttrService: service,
            kSecAttrAccount: key,
        ]
        SecItemDelete(query as CFDictionary)
    }

    // MARK: - Convenience: Anthropic API Key

    static var anthropicAPIKey: String? {
        get { try? load(forKey: "anthropicAPIKey") }
        set {
            if let value = newValue {
                try? save(value, forKey: "anthropicAPIKey")
            } else {
                delete(forKey: "anthropicAPIKey")
            }
        }
    }

    // MARK: - Error

    enum KeychainError: LocalizedError {
        case encodingFailed
        case saveFailed(OSStatus)
        case loadFailed(OSStatus)

        var errorDescription: String? {
            switch self {
            case .encodingFailed:       return "Не удалось закодировать данные"
            case .saveFailed(let s):    return "Ошибка сохранения Keychain: \(s)"
            case .loadFailed(let s):    return "Ошибка чтения Keychain: \(s)"
            }
        }
    }
}
