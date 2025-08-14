import SwiftUI
import AppKit
import Foundation

@main
struct HuddleIndicatorApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var appDelegate
    
    var body: some Scene {
        Settings {
            EmptyView()
        }
    }
}

class AppDelegate: NSObject, NSApplicationDelegate {
    var statusItem: NSStatusItem?
    var popover: NSPopover?
    var statusManager: HuddleStatusManager?
    
    func applicationDidFinishLaunching(_ notification: Notification) {
        setupMenuBar()
        setupPopover()
        setupStatusManager()
        print("DEBUG: App launched successfully")
    }
    
    private func setupMenuBar() {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        
        if let button = statusItem?.button {
            button.title = "⚪️"  // White circle for better visibility
            button.action = #selector(togglePopover)
            button.target = self
        }
    }
    
    private func setupPopover() {
        popover = NSPopover()
        popover?.contentSize = NSSize(width: 300, height: 200)
        popover?.behavior = .transient
        // We'll set the content view controller after status manager is created
    }
    
    private func setupStatusManager() {
        statusManager = HuddleStatusManager(appDelegate: self)
        // Now set up the popover content with the status manager
        popover?.contentViewController = NSHostingController(rootView: HuddleStatusView(statusManager: statusManager!))
    }
    
    func updateMenuBarIcon(inHuddle: Bool) {
        guard let button = statusItem?.button else {
            print("DEBUG: No status button available")
            return
        }
        
        let newTitle = inHuddle ? "🎙️" : "⚪️"
        print("DEBUG: Updating icon to \(newTitle) (inHuddle: \(inHuddle))")
        button.title = newTitle
    }
    
    @objc func togglePopover() {
        if let popover = popover {
            if popover.isShown {
                popover.performClose(nil)
            } else {
                if let button = statusItem?.button {
                    popover.show(relativeTo: button.bounds, of: button, preferredEdge: NSRectEdge.minY)
                }
            }
        }
    }
}

struct HuddleStatus: Codable {
    let inHuddle: Bool
    let score: Int
    let baseline: Double
    let peakScore: Int
    let trend: String
    let timestamp: String
    let metrics: HuddleMetrics
}

struct HuddleMetrics: Codable {
    let slackAssertions: Int
    let audioUnits: Int
    let audioFds: Int
    let powerAssertions: Int
}

class HuddleStatusManager: ObservableObject {
    @Published var status: HuddleStatus?
    @Published var isConnected = false
    
    private var timer: Timer?
    private let statusFilePath = "/tmp/huddle-status-\(NSUserName()).json"
    private weak var appDelegate: AppDelegate?
    
    init(appDelegate: AppDelegate) {
        print("DEBUG: HuddleStatusManager init")
        self.appDelegate = appDelegate
        startPolling()
    }
    
    private func startPolling() {
        timer = Timer.scheduledTimer(withTimeInterval: 2.0, repeats: true) { _ in
            self.loadStatus()
        }
        loadStatus()
    }
    
    private func loadStatus() {
        print("DEBUG: Checking status file at \(statusFilePath)")
        
        guard let data = try? Data(contentsOf: URL(fileURLWithPath: statusFilePath)) else {
            print("DEBUG: Could not read status file")
            DispatchQueue.main.async {
                self.isConnected = false
                self.status = nil
                self.appDelegate?.updateMenuBarIcon(inHuddle: false)
            }
            return
        }
        
        guard let status = try? JSONDecoder().decode(HuddleStatus.self, from: data) else {
            print("DEBUG: Could not decode JSON")
            DispatchQueue.main.async {
                self.isConnected = false
                self.status = nil
                self.appDelegate?.updateMenuBarIcon(inHuddle: false)
            }
            return
        }
        
        print("DEBUG: Successfully loaded status - inHuddle: \(status.inHuddle), score: \(status.score)")
        
        DispatchQueue.main.async {
            self.isConnected = true
            self.status = status
            self.appDelegate?.updateMenuBarIcon(inHuddle: status.inHuddle)
        }
    }
    
    
    deinit {
        timer?.invalidate()
    }
}

struct HuddleStatusView: View {
    @ObservedObject var statusManager: HuddleStatusManager
    
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("Slack Huddle Detector")
                    .font(.headline)
                Spacer()
                Circle()
                    .fill(statusManager.isConnected ? .green : .red)
                    .frame(width: 8, height: 8)
            }
            
            if let status = statusManager.status {
                VStack(alignment: .leading, spacing: 8) {
                    HStack {
                        Text(status.inHuddle ? "🎙️ IN HUDDLE" : "⚪️ Not in huddle")
                            .font(.title2)
                            .fontWeight(.semibold)
                        Spacer()
                    }
                    
                    HStack {
                        Text("Score:")
                        Text("\(status.score)")
                            .fontWeight(.medium)
                        Text("(\(status.trend))")
                            .foregroundColor(.secondary)
                        Spacer()
                        Text("Baseline: \(String(format: "%.0f", status.baseline))")
                            .foregroundColor(.secondary)
                    }
                    
                    if status.inHuddle {
                        Text("Peak: \(status.peakScore)")
                            .foregroundColor(.secondary)
                    }
                    
                    Divider()
                    
                    Text("Metrics")
                        .font(.subheadline)
                        .fontWeight(.medium)
                    
                    HStack {
                        MetricView(label: "PWR", value: status.metrics.slackAssertions)
                        MetricView(label: "AU", value: status.metrics.audioUnits)
                        MetricView(label: "FD", value: status.metrics.audioFds)
                    }
                    
                    HStack {
                        Text("Updated:")
                        Text(status.timestamp)
                        Spacer()
                    }
                    .font(.caption)
                    .foregroundColor(.secondary)
                }
            } else {
                VStack {
                    Text("❌ No detector running")
                        .font(.title2)
                    Text("Start the Python detector to see status")
                        .foregroundColor(.secondary)
                        .multilineTextAlignment(.center)
                }
            }
        }
        .padding()
    }
}

struct MetricView: View {
    let label: String
    let value: Int
    
    var body: some View {
        VStack {
            Text(label)
                .font(.caption)
                .foregroundColor(.secondary)
            Text("\(value)")
                .font(.title3)
                .fontWeight(.medium)
        }
        .frame(minWidth: 30)
    }
}