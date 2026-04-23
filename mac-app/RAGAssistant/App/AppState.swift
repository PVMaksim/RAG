import SwiftUI
import Combine

// MARK: - AppState

/// Централизованное состояние приложения.
/// Передаётся через environmentObject во все View.
final class AppState: ObservableObject {

    // Backend connectivity
    @Published var backendOnline: Bool = false
    @Published var backendURL: String {
        didSet { UserDefaults.standard.backendURL = backendURL }
    }

    // Hotkey
    @Published var hotkeyEnabled: Bool = true

    private var healthTimer: Timer?
    private var cancellables = Set<AnyCancellable>()

    init() {
        self.backendURL = UserDefaults.standard.backendURL
        startHealthPolling()
    }

    deinit {
        healthTimer?.invalidate()
    }

    // MARK: - Health Polling

    func startHealthPolling() {
        checkHealth()
        healthTimer = Timer.scheduledTimer(withTimeInterval: 15, repeats: true) { [weak self] _ in
            self?.checkHealth()
        }
    }

    func checkHealth() {
        guard let url = URL(string: backendURL + "/health") else { return }
        URLSession.shared.dataTask(with: url) { [weak self] _, response, _ in
            let ok = (response as? HTTPURLResponse)?.statusCode == 200
            DispatchQueue.main.async {
                self?.backendOnline = ok
            }
        }.resume()
    }
}

// MARK: - UserDefaults extensions

extension UserDefaults {
    private enum Keys {
        static let backendURL = "backendURL"
    }

    var backendURL: String {
        get { string(forKey: Keys.backendURL) ?? "http://localhost:8080" }
        set { set(newValue, forKey: Keys.backendURL) }
    }
}
