// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "HuddleIndicator",
    platforms: [
        .macOS(.v14)
    ],
    products: [
        .executable(
            name: "HuddleIndicator",
            targets: ["HuddleIndicator"]
        ),
    ],
    targets: [
        .executableTarget(
            name: "HuddleIndicator",
            dependencies: [],
            path: "Sources"
        ),
    ]
)