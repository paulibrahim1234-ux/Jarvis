import Foundation
import AppKit

// Keep references to prevent deallocation
let appDelegate = AppDelegate()

let app = NSApplication.shared
app.setActivationPolicy(.accessory) // menubar-only app, no dock icon
app.delegate = appDelegate
app.run()
