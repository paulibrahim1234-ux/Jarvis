// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "JarvisNative",
    platforms: [
        .macOS(.v13)
    ],
    products: [
        .executable(name: "JarvisNative", targets: ["JarvisNative"])
    ],
    dependencies: [
        .package(url: "https://github.com/swhitty/FlyingFox.git", from: "0.20.0")
    ],
    targets: [
        .executableTarget(
            name: "JarvisNative",
            dependencies: [
                .product(name: "FlyingFox", package: "FlyingFox")
            ],
            path: "Sources/JarvisNative",
            linkerSettings: [
                .linkedLibrary("sqlite3")
            ]
        )
    ]
)
