import Carbon
import AppKit

// MARK: - HotkeyService

/// Глобальный хоткей ⌥Space — открывает/закрывает popup menu bar окно.
/// Использует Carbon RegisterEventHotKey.
///
/// ИСПРАВЛЕНИЕ: убран Unmanaged.passRetained (потенциальный memory leak).
/// Вместо него используется глобальная слабая ссылка через статический словарь.
final class HotkeyService {

    static let shared = HotkeyService()

    private var hotKeyRef: EventHotKeyRef?
    private var eventHandler: EventHandlerRef?
    var onTrigger: (() -> Void)?

    private init() {}

    deinit {
        unregister()
    }

    // MARK: - Public API

    func register(onTrigger: @escaping () -> Void) {
        self.onTrigger = onTrigger

        // Регистрируем в глобальном реестре чтобы не использовать Unmanaged retain
        HotkeyRegistry.shared.register(self)

        let hotKeyID = EventHotKeyID(signature: fourCharCode("RAGA"), id: 1)
        let keyCode:   UInt32 = 49               // kVK_Space
        let modifiers: UInt32 = UInt32(optionKey) // ⌥

        var eventType = EventTypeSpec(
            eventClass: OSType(kEventClassKeyboard),
            eventKind:  UInt32(kEventHotKeyPressed)
        )

        // Используем статический callback — не захватывает self напрямую
        InstallEventHandler(
            GetApplicationEventTarget(),
            HotkeyService.globalEventCallback,
            1,
            &eventType,
            nil,       // userData = nil, используем HotkeyRegistry
            &eventHandler
        )

        RegisterEventHotKey(
            keyCode, modifiers, hotKeyID,
            GetApplicationEventTarget(), 0, &hotKeyRef
        )
    }

    func unregister() {
        HotkeyRegistry.shared.unregister()
        if let ref = hotKeyRef {
            UnregisterEventHotKey(ref)
            hotKeyRef = nil
        }
        if let handler = eventHandler {
            RemoveEventHandler(handler)
            eventHandler = nil
        }
    }

    // MARK: - Static Carbon Callback (не захватывает self → нет retain цикла)

    private static let globalEventCallback: EventHandlerUPP = { _, _, _ -> OSStatus in
        DispatchQueue.main.async {
            HotkeyRegistry.shared.currentService?.onTrigger?()
        }
        return noErr
    }

    // MARK: - Helpers

    private func fourCharCode(_ string: String) -> FourCharCode {
        var result: FourCharCode = 0
        for char in string.utf8.prefix(4) {
            result = (result << 8) + FourCharCode(char)
        }
        return result
    }
}

// MARK: - HotkeyRegistry

/// Слабая ссылка на текущий HotkeyService.
/// Позволяет Carbon callback вызывать onTrigger без захвата self.
final class HotkeyRegistry {
    static let shared = HotkeyRegistry()
    private init() {}

    private(set) weak var currentService: HotkeyService?

    func register(_ service: HotkeyService) {
        currentService = service
    }

    func unregister() {
        currentService = nil
    }
}
