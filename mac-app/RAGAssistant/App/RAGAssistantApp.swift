import SwiftUI

@main
struct RAGAssistantApp: App {

    @StateObject private var appState = AppState()
    @NSApplicationDelegateAdaptor(AppDelegate.self) var delegate
    @Environment(\.openWindow) private var openWindow

    // Открываем onboarding при первом запуске
    func openOnboardingIfNeeded() {
        // openWindow вызывается из body — используем через notification
        if !UserDefaults.standard.bool(forKey: "onboardingCompleted") {
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) {
                NSApp.sendAction(Selector(("showOnboarding:")), to: nil, from: nil)
            }
        }
    }

    var body: some Scene {
        // Menu bar иконка — главная точка входа
        MenuBarExtra {
            MenuBarView()
                .environmentObject(appState)
        } label: {
            MenuBarLabel()
                .environmentObject(appState)
        }
        .menuBarExtraStyle(.window)

        // Настройки (⌘, или через меню)
        Settings {
            SettingsView()
                .environmentObject(appState)
        }

        // Onboarding — показывается при первом запуске
        WindowGroup("Добро пожаловать", id: "onboarding") {
            if appState.isOnboardingNeeded {
                OnboardingView()
                    .environmentObject(appState)
            }
        }
        .windowResizability(.contentSize)
        .defaultPosition(.center)
    }
}

// MARK: - Menu Bar Label (иконка)

struct MenuBarLabel: View {
    @EnvironmentObject var appState: AppState

    var body: some View {
        HStack(spacing: 4) {
            Image(systemName: "magnifyingglass.circle.fill")
                .symbolRenderingMode(.hierarchical)
                .foregroundStyle(appState.backendOnline ? .blue : .secondary)
        }
    }
}
