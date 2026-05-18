import Foundation
import AVFoundation
import Speech

/// On-device speech recognition + speech synthesis for Jarvis.
/// Mirrors the singleton pattern used by CalendarService / MessagesService.
@MainActor
final class VoiceService {
    static let shared = VoiceService()

    // MARK: - Recognition state

    private let recognizer: SFSpeechRecognizer? = SFSpeechRecognizer(locale: Locale(identifier: "en-US"))
    private let audioEngine = AVAudioEngine()
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private var task: SFSpeechRecognitionTask?

    /// Latest partial transcription. HTTP `/voice/listen/stop` reads this.
    private(set) var lastPartial: String = ""

    // MARK: - Synthesis state

    private let synthesizer = AVSpeechSynthesizer()

    private init() {}

    // MARK: - Permissions

    /// Requests Speech + Microphone authorization. Returns true only if BOTH granted.
    func requestPermissions() async -> Bool {
        let speech: SFSpeechRecognizerAuthorizationStatus = await withCheckedContinuation { cont in
            SFSpeechRecognizer.requestAuthorization { status in
                cont.resume(returning: status)
            }
        }
        guard speech == .authorized else {
            NSLog("VoiceService: speech auth denied (status=\(speech.rawValue))")
            return false
        }

        let mic: Bool = await withCheckedContinuation { cont in
            AVCaptureDevice.requestAccess(for: .audio) { granted in
                cont.resume(returning: granted)
            }
        }
        if !mic { NSLog("VoiceService: microphone access denied") }
        return mic
    }

    // MARK: - Listening

    enum VoiceError: Error {
        case recognizerUnavailable
        case alreadyListening
        case engineStartFailed(String)
    }

    /// Starts AVAudioEngine + SFSpeechAudioBufferRecognitionRequest, yields partials.
    /// Prefers on-device recognition; falls back to cloud if unsupported.
    func startListening() async throws -> AsyncStream<String> {
        guard let recognizer = recognizer, recognizer.isAvailable else {
            throw VoiceError.recognizerUnavailable
        }
        if task != nil || request != nil {
            throw VoiceError.alreadyListening
        }

        lastPartial = ""

        let req = SFSpeechAudioBufferRecognitionRequest()
        req.shouldReportPartialResults = true
        if recognizer.supportsOnDeviceRecognition {
            req.requiresOnDeviceRecognition = true
        }
        self.request = req

        let inputNode = audioEngine.inputNode
        let format = inputNode.outputFormat(forBus: 0)
        // Remove any prior tap defensively
        inputNode.removeTap(onBus: 0)
        inputNode.installTap(onBus: 0, bufferSize: 1024, format: format) { [weak self] buffer, _ in
            // Tap runs on a non-main thread; just append — SFSpeechAudioBufferRecognitionRequest is thread-safe for append.
            self?.request?.append(buffer)
        }

        audioEngine.prepare()
        do {
            try audioEngine.start()
        } catch {
            inputNode.removeTap(onBus: 0)
            self.request = nil
            throw VoiceError.engineStartFailed(error.localizedDescription)
        }

        let stream = AsyncStream<String> { [weak self] continuation in
            guard let self = self else {
                continuation.finish()
                return
            }
            self.task = recognizer.recognitionTask(with: req) { [weak self] result, error in
                if let result = result {
                    let text = result.bestTranscription.formattedString
                    Task { @MainActor [weak self] in
                        self?.lastPartial = text
                    }
                    continuation.yield(text)
                    if result.isFinal {
                        continuation.finish()
                    }
                }
                if error != nil {
                    continuation.finish()
                }
            }
            continuation.onTermination = { @Sendable _ in
                Task { @MainActor [weak self] in
                    self?.teardown()
                }
            }
        }
        return stream
    }

    func stopListening() {
        teardown()
    }

    private func teardown() {
        if audioEngine.isRunning {
            audioEngine.stop()
        }
        audioEngine.inputNode.removeTap(onBus: 0)
        request?.endAudio()
        task?.cancel()
        request = nil
        task = nil
    }

    // MARK: - Speaking

    /// Speaks `text` asynchronously. `voice` is an AVSpeechSynthesisVoice identifier or nil.
    func speak(_ text: String, voice: String? = nil) {
        let utterance = AVSpeechUtterance(string: text)
        if let voiceID = voice, let v = AVSpeechSynthesisVoice(identifier: voiceID) {
            utterance.voice = v
        } else {
            utterance.voice = AVSpeechSynthesisVoice(language: "en-US")
        }
        synthesizer.speak(utterance)
    }

    func stopSpeaking() {
        synthesizer.stopSpeaking(at: .immediate)
    }
}
