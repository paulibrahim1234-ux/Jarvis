import Foundation
import AppKit

final class AppDelegate: NSObject, NSApplicationDelegate {
    var statusItem: NSStatusItem?
    var httpServer: HTTPServer?

    func applicationDidFinishLaunching(_ notification: Notification) {
        setupMenuBar()

        // Request permissions early so the user sees dialogs on first run
        CalendarService.shared.requestAccess { granted in
            NSLog("Calendar access granted: \(granted)")
        }
        ContactsService.shared.requestAccess { granted in
            NSLog("Contacts access granted: \(granted)")
        }

        // Start HTTP server on :8764
        httpServer = HTTPServer()
        Task {
            do {
                try await httpServer?.start(port: 8764)
            } catch {
                NSLog("HTTP server failed: \(error)")
            }
        }
    }

    func setupMenuBar() {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        if let button = statusItem?.button {
            button.title = "J"
            button.toolTip = "Jarvis Native — port 8764"
        }

        let menu = NSMenu()
        menu.addItem(NSMenuItem(title: "Jarvis Native (port 8764)", action: nil, keyEquivalent: ""))
        menu.addItem(NSMenuItem.separator())
        menu.addItem(NSMenuItem(title: "Open Health Check", action: #selector(openHealth), keyEquivalent: "h"))
        menu.addItem(NSMenuItem(title: "Request Permissions", action: #selector(requestPermissions), keyEquivalent: "p"))
        menu.addItem(NSMenuItem.separator())
        menu.addItem(NSMenuItem(title: "Quit", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q"))
        statusItem?.menu = menu
    }

    @objc func openHealth() {
        if let url = URL(string: "http://localhost:8764/health") {
            NSWorkspace.shared.open(url)
        }
    }

    @objc func requestPermissions() {
        CalendarService.shared.requestAccess { _ in }
        ContactsService.shared.requestAccess { _ in }
    }
}
