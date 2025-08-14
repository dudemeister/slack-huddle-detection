import Foundation

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

let statusFilePath = "/tmp/huddle-status.json"

do {
    let data = try Data(contentsOf: URL(fileURLWithPath: statusFilePath))
    let status = try JSONDecoder().decode(HuddleStatus.self, from: data)
    print("✅ Successfully decoded JSON:")
    print("  inHuddle: \(status.inHuddle)")
    print("  score: \(status.score)")
    print("  baseline: \(status.baseline)")
    print("  Should show: \(status.inHuddle ? "🎙️" : "⚪️")")
} catch {
    print("❌ Error: \(error)")
}