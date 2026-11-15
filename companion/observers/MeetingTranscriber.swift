import AppKit
import AVFoundation
import CoreGraphics
import CoreMedia
import Darwin
import Foundation
import Speech
#if canImport(ScreenCaptureKit)
import ScreenCaptureKit
#endif

func emit(_ fields: [String: Any]) {
    var value = fields
    value["at"] = Date().timeIntervalSince1970
    guard let data = try? JSONSerialization.data(withJSONObject: value, options: [.sortedKeys]) else { return }
    FileHandle.standardOutput.write(data + Data([10]))
}

func status(_ state: String, _ detail: String, source: String = "all") {
    emit(["type": "status", "state": state, "detail": detail, "source": source])
}

func errorCode(_ error: Error) -> String {
    let value = error as NSError
    return "\(value.domain):\(value.code)"
}

struct Options {
    let locale: String
    let session: String
    let capture: String

    static func parse() throws -> Options {
        let args = Array(CommandLine.arguments.dropFirst())
        guard args.count % 2 == 0 else { throw Failure.invalidArguments }
        var values: [String: String] = [:]
        for index in stride(from: 0, to: args.count, by: 2) {
            let name = args[index]
            guard ["--locale", "--session", "--capture"].contains(name), values[name] == nil else {
                throw Failure.invalidArguments
            }
            values[name] = args[index + 1]
        }
        guard let session = values["--session"], UUID(uuidString: session) != nil else {
            throw Failure.invalidArguments
        }
        let capture = values["--capture"] ?? "microphone"
        let locale = values["--locale"] ?? "zh-CN"
        guard ["microphone", "system", "both"].contains(capture),
              !locale.isEmpty, locale.utf8.count <= 80 else { throw Failure.invalidArguments }
        return Options(locale: locale, session: session, capture: capture)
    }
}

enum Failure: Error {
    case invalidArguments
    case recognizerUnavailable
    case microphoneUnavailable
    case displayUnavailable
}

@available(macOS 10.15, *)
final class SpeechLane {
    let source: String
    let recognizer: SFSpeechRecognizer
    let session: String
    let onFailure: (String) -> Void
    let onFinished: () -> Void
    private let inputLock = NSLock()
    private var input: SFSpeechAudioBufferRecognitionRequest?
    private var active: SFSpeechAudioBufferRecognitionRequest?
    private var pending: SFSpeechAudioBufferRecognitionRequest?
    private var task: SFSpeechRecognitionTask?
    private var timer: Timer?
    private var drainTimer: Timer?
    private var generation = 0
    private var activeStart = 0.0
    private var activeEnd: Double?
    private var pendingStart = 0.0
    private var stoppedAt: Double?
    private var stopping = false
    private var finished = false

    init(source: String, options: Options, onFailure: @escaping (String) -> Void,
         onFinished: @escaping () -> Void) throws {
        guard let recognizer = SFSpeechRecognizer(locale: Locale(identifier: options.locale)),
              recognizer.isAvailable, recognizer.supportsOnDeviceRecognition else {
            throw Failure.recognizerUnavailable
        }
        self.source = source
        self.recognizer = recognizer
        self.session = options.session
        self.onFailure = onFailure
        self.onFinished = onFinished
    }

    func start() {
        let request = makeRequest()
        inputLock.lock()
        input = request
        inputLock.unlock()
        begin(request, startedAt: Date().timeIntervalSince1970)
    }

    func append(_ buffer: AVAudioPCMBuffer) {
        inputLock.lock()
        input?.append(buffer)
        inputLock.unlock()
    }

    func append(_ buffer: CMSampleBuffer) {
        guard buffer.isValid else { return }
        inputLock.lock()
        input?.appendAudioSampleBuffer(buffer)
        inputLock.unlock()
    }

    func finish() {
        guard !finished, !stopping else { return }
        stopping = true
        stoppedAt = Date().timeIntervalSince1970
        timer?.invalidate()
        inputLock.lock()
        let receiving = input
        input = nil
        inputLock.unlock()
        activeEnd = activeEnd ?? stoppedAt
        receiving?.endAudio()
        if receiving !== active { active?.endAudio() }
        if task == nil { complete() }
    }

    func cancel() {
        inputLock.lock()
        input = nil
        inputLock.unlock()
        timer?.invalidate()
        drainTimer?.invalidate()
        task?.cancel()
        task = nil
        pending = nil
        complete()
    }

    private func makeRequest() -> SFSpeechAudioBufferRecognitionRequest {
        let request = SFSpeechAudioBufferRecognitionRequest()
        request.requiresOnDeviceRecognition = true
        request.shouldReportPartialResults = false
        request.taskHint = .dictation
        return request
    }

    private func begin(_ request: SFSpeechAudioBufferRecognitionRequest, startedAt: Double) {
        guard !finished else { return }
        generation += 1
        let current = generation
        active = request
        activeStart = startedAt
        activeEnd = stoppedAt
        task = recognizer.recognitionTask(with: request) { [weak self] result, error in
            DispatchQueue.main.async {
                self?.receive(result, error: error, generation: current)
            }
        }
        if !stopping {
            timer = Timer.scheduledTimer(withTimeInterval: 50, repeats: false) { [weak self] _ in
                self?.rotate()
            }
        }
    }

    private func rotate() {
        guard !stopping, !finished, pending == nil else { return }
        let next = makeRequest()
        pendingStart = Date().timeIntervalSince1970
        pending = next
        activeEnd = pendingStart
        // The next request buffers input while the old task finishes. No raw
        // audio is written to disk, and the pending interval has a hard limit.
        inputLock.lock()
        input = next
        inputLock.unlock()
        active?.endAudio()
        drainTimer = Timer.scheduledTimer(withTimeInterval: 10, repeats: false) { [weak self] _ in
            guard let self = self, self.pending != nil else { return }
            self.onFailure("speech_finalization_timeout")
        }
    }

    private func receive(_ result: SFSpeechRecognitionResult?, error: Error?, generation current: Int) {
        guard !finished, current == generation else { return }
        let noSpeech = (error as NSError?)?.domain == "kAFAssistantErrorDomain"
            && (error as NSError?)?.code == 1110
        if let error = error, !noSpeech {
            onFailure("speech_" + errorCode(error))
            return
        }
        guard result?.isFinal == true || noSpeech else { return }
        if let text = result?.bestTranscription.formattedString, !text.isEmpty {
            emit(["type": "transcript", "text": text, "source": source,
                  "segment": "\(session):\(source):\(current)", "final": true,
                  "started_at": activeStart, "ended_at": activeEnd ?? Date().timeIntervalSince1970])
        }
        timer?.invalidate()
        drainTimer?.invalidate()
        task = nil
        if let next = pending {
            pending = nil
            begin(next, startedAt: pendingStart)
        } else if stopping {
            complete()
        } else {
            let next = makeRequest()
            inputLock.lock()
            input = next
            inputLock.unlock()
            begin(next, startedAt: Date().timeIntervalSince1970)
        }
    }

    private func complete() {
        guard !finished else { return }
        finished = true
        timer?.invalidate()
        drainTimer?.invalidate()
        onFinished()
    }
}

protocol SystemAudioCapture: AnyObject {
    func start(_ completion: @escaping (Error?) -> Void)
    func stop(_ completion: @escaping () -> Void)
}

#if canImport(ScreenCaptureKit)
@available(macOS 13.0, *)
final class ScreenAudio: NSObject, SystemAudioCapture, SCStreamOutput, SCStreamDelegate {
    private var capture: SCStream?
    private let lane: SpeechLane
    private let onFailure: (String) -> Void
    private var stopping = false

    init(lane: SpeechLane, onFailure: @escaping (String) -> Void) {
        self.lane = lane
        self.onFailure = onFailure
    }

    func start(_ completion: @escaping (Error?) -> Void) {
        SCShareableContent.getExcludingDesktopWindows(true, onScreenWindowsOnly: true) { content, error in
            DispatchQueue.main.async {
                guard !self.stopping else { completion(Failure.displayUnavailable); return }
                if let error = error { completion(error); return }
                guard let display = content?.displays.first(where: { $0.displayID == CGMainDisplayID() })
                        ?? content?.displays.first else { completion(Failure.displayUnavailable); return }
                let filter = SCContentFilter(display: display, excludingWindows: [])
                let configuration = SCStreamConfiguration()
                configuration.capturesAudio = true
                configuration.excludesCurrentProcessAudio = true
                configuration.sampleRate = 16000
                configuration.channelCount = 1
                configuration.width = 2
                configuration.height = 2
                configuration.minimumFrameInterval = CMTime(value: 1, timescale: 1)
                let stream = SCStream(filter: filter, configuration: configuration, delegate: self)
                self.capture = stream
                do {
                    // No screen output is registered or persisted.
                    try stream.addStreamOutput(self, type: .audio,
                                               sampleHandlerQueue: DispatchQueue(label: "localpilot.meeting.audio"))
                    stream.startCapture { error in
                        DispatchQueue.main.async { completion(error) }
                    }
                } catch { completion(error) }
            }
        }
    }

    func stop(_ completion: @escaping () -> Void) {
        stopping = true
        guard let capture = capture else { completion(); return }
        capture.stopCapture { _ in DispatchQueue.main.async { completion() } }
    }

    func stream(_ stream: SCStream, didOutputSampleBuffer sampleBuffer: CMSampleBuffer,
                of outputType: SCStreamOutputType) {
        if outputType == .audio { lane.append(sampleBuffer) }
    }

    func stream(_ stream: SCStream, didStopWithError error: Error) {
        DispatchQueue.main.async {
            if !self.stopping { self.onFailure("system_audio_" + errorCode(error)) }
        }
    }
}
#endif

@available(macOS 10.15, *)
final class Meeting {
    private let options: Options
    private let microphone = AVAudioEngine()
    private var microphoneStarted = false
    private var lanes: [String: SpeechLane] = [:]
    private var systemAudio: SystemAudioCapture?
    private var stopping = false
    private var systemStopped = true
    private var finishedLanes: Set<String> = []
    private var finalState = "stopped"
    private var finalDetail = "user_stopped"
    private var terminationTimer: Timer?

    init(_ options: Options) { self.options = options }

    func start() {
        status("starting", "requesting_speech_permission")
        SFSpeechRecognizer.requestAuthorization { authorization in
            DispatchQueue.main.async {
                guard !self.stopping else { return }
                guard authorization == .authorized else {
                    self.stop(state: "denied", detail: "speech_permission_required"); return
                }
                if self.options.capture == "system" { self.prepare(); return }
                AVCaptureDevice.requestAccess(for: .audio) { granted in
                    DispatchQueue.main.async {
                        guard !self.stopping else { return }
                        if granted { self.prepare() }
                        else { self.stop(state: "denied", detail: "microphone_permission_required") }
                    }
                }
            }
        }
    }

    func stop(state: String = "stopped", detail: String = "user_stopped") {
        guard !stopping else { return }
        stopping = true
        finalState = state
        finalDetail = detail
        status("stopping", detail)
        if microphoneStarted {
            microphone.stop()
            microphone.inputNode.removeTap(onBus: 0)
            microphoneStarted = false
        }
        terminationTimer = Timer.scheduledTimer(withTimeInterval: 10, repeats: false) { [weak self] _ in
            guard let self = self else { return }
            status(self.finalState == "stopped" ? "failed" : self.finalState,
                   self.finalState == "stopped" ? "final_transcript_incomplete" : self.finalDetail)
            exit(1)
        }
        if state == "stopped" { lanes.values.forEach { $0.finish() } }
        else { lanes.values.forEach { $0.cancel() } }
        systemAudio?.stop {
            self.systemStopped = true
            self.completeIfStopped()
        }
        completeIfStopped()
    }

    private func prepare() {
        do {
            let sources = options.capture == "both" ? ["mic", "system"] :
                          options.capture == "system" ? ["system"] : ["mic"]
            for source in sources {
                lanes[source] = try SpeechLane(source: source, options: options,
                    onFailure: { detail in self.stop(state: "failed", detail: detail) },
                    onFinished: { self.finishedLanes.insert(source); self.completeIfStopped() })
            }
            if let lane = lanes["system"] {
                #if canImport(ScreenCaptureKit)
                if #available(macOS 13.0, *) {
                    guard CGPreflightScreenCaptureAccess() || CGRequestScreenCaptureAccess() else {
                        stop(state: "denied", detail: "system_audio_screen_recording_permission_required"); return
                    }
                    systemAudio = ScreenAudio(lane: lane, onFailure: { self.stop(state: "failed", detail: $0) })
                } else {
                    stop(state: "unavailable", detail: "system_audio_requires_macos_13"); return
                }
                #else
                stop(state: "unavailable", detail: "screen_capture_sdk_unavailable"); return
                #endif
            }
            lanes.values.forEach { $0.start() }
            if let lane = lanes["mic"] {
                let node = microphone.inputNode
                let format = node.outputFormat(forBus: 0)
                guard format.sampleRate > 0, format.channelCount > 0 else { throw Failure.microphoneUnavailable }
                node.installTap(onBus: 0, bufferSize: 2048, format: format) { buffer, _ in lane.append(buffer) }
                microphoneStarted = true
                microphone.prepare()
                try microphone.start()
            }
            if let systemAudio = systemAudio {
                systemStopped = false
                systemAudio.start { error in
                    guard !self.stopping else { return }
                    if let error = error { self.stop(state: "failed", detail: "system_audio_" + errorCode(error)) }
                    else { status("recording", "on_device_" + self.options.capture) }
                }
            } else { status("recording", "on_device_microphone") }
        } catch Failure.recognizerUnavailable {
            stop(state: "unavailable", detail: "on_device_speech_unavailable_for_locale")
        } catch { stop(state: "failed", detail: "capture_" + errorCode(error)) }
    }

    private func completeIfStopped() {
        guard stopping, systemStopped, finishedLanes.count == lanes.count else { return }
        terminationTimer?.invalidate()
        status(finalState, finalDetail)
        exit(finalState == "stopped" ? 0 : 1)
    }
}

do {
    let options = try Options.parse()
    if #available(macOS 10.15, *) {
        let app = NSApplication.shared
        app.setActivationPolicy(.accessory)
        let meeting = Meeting(options)
        signal(SIGTERM, SIG_IGN)
        signal(SIGINT, SIG_IGN)
        let signals = [SIGTERM, SIGINT].map { number -> DispatchSourceSignal in
            let source = DispatchSource.makeSignalSource(signal: number, queue: .main)
            source.setEventHandler { meeting.stop(detail: "host_terminated") }
            source.resume()
            return source
        }
        DispatchQueue.global(qos: .utility).async {
            while let line = readLine() {
                if line == "stop" { break }
            }
            DispatchQueue.main.async { meeting.stop(detail: "host_stopped") }
        }
        meeting.start()
        withExtendedLifetime((meeting, signals)) { app.run() }
    } else {
        status("unavailable", "speech_requires_macos_10_15")
        exit(1)
    }
} catch {
    status("failed", "invalid_arguments")
    exit(2)
}
