import Foundation
import FlyingFox

final class HTTPServer {
    private var server: FlyingFox.HTTPServer?

    func start(port: UInt16) async throws {
        let s = FlyingFox.HTTPServer(port: port)
        self.server = s

        // GET /health
        await s.appendRoute("GET /health") { _ in
            let body: [String: Any] = [
                "ok": true,
                "version": "0.1.0",
                "endpoints": [
                    "/health",
                    "/calendar/events?days=N",
                    "/messages/conversations?limit=N",
                    "/contacts/search?q=...",
                    "/voice/listen/start",
                    "/voice/listen/stop",
                    "/voice/speak"
                ]
            ]
            return Self.jsonResponse(body)
        }

        // GET /calendar/events?days=30
        await s.appendRoute("GET /calendar/events") { request in
            let days = Self.intQuery(request, name: "days") ?? 30
            let events = await CalendarService.shared.events(daysAhead: days)
            return Self.jsonResponse(["events": events])
        }

        // GET /messages/conversations?limit=25
        await s.appendRoute("GET /messages/conversations") { request in
            let limit = Self.intQuery(request, name: "limit") ?? 25
            let (convos, err) = MessagesService.shared.conversations(limit: limit)
            if let err {
                return Self.jsonResponse(["error": err, "conversations": []], status: .internalServerError)
            }
            return Self.jsonResponse(["conversations": convos])
        }

        // GET /contacts/search?q=...
        await s.appendRoute("GET /contacts/search") { request in
            let q = Self.stringQuery(request, name: "q") ?? ""
            let results = await ContactsService.shared.search(query: q)
            return Self.jsonResponse(["results": results])
        }

        // POST /voice/listen/start
        // Kicks off speech recognition; does NOT block on the transcription.
        // Streaming-to-HTTP can come later; for now we just confirm we started.
        await s.appendRoute("POST /voice/listen/start") { _ in
            do {
                // Fire-and-forget the stream — VoiceService keeps `lastPartial` updated.
                let stream = try await VoiceService.shared.startListening()
                Task.detached {
                    for await _ in stream { /* drain; lastPartial is what /stop reads */ }
                }
                return Self.jsonResponse(["ok": true, "status": "listening"])
            } catch {
                return Self.jsonResponse(
                    ["ok": false, "error": "\(error)"],
                    status: .internalServerError
                )
            }
        }

        // POST /voice/listen/stop
        await s.appendRoute("POST /voice/listen/stop") { _ in
            await VoiceService.shared.stopListening()
            let final = await VoiceService.shared.lastPartial
            return Self.jsonResponse(["ok": true, "final": final])
        }

        // POST /voice/speak  body: {"text": "...", "voice": "..."}
        await s.appendRoute("POST /voice/speak") { request in
            let payload = (try? await Self.decodeJSONBody(request)) ?? [:]
            let text = (payload["text"] as? String) ?? ""
            let voice = payload["voice"] as? String
            guard !text.isEmpty else {
                return Self.jsonResponse(
                    ["ok": false, "error": "missing text"],
                    status: .badRequest
                )
            }
            await VoiceService.shared.speak(text, voice: voice)
            return Self.jsonResponse(["ok": true])
        }

        NSLog("HTTP server listening on port \(port)")
        try await s.run()
    }

    // MARK: helpers

    private static func intQuery(_ req: FlyingFox.HTTPRequest, name: String) -> Int? {
        for q in req.query where q.name == name {
            return Int(q.value)
        }
        return nil
    }

    private static func stringQuery(_ req: FlyingFox.HTTPRequest, name: String) -> String? {
        for q in req.query where q.name == name {
            return q.value
        }
        return nil
    }

    /// Reads the request body and decodes it as a JSON object.
    private static func decodeJSONBody(_ req: FlyingFox.HTTPRequest) async throws -> [String: Any] {
        let data = try await req.bodyData
        guard !data.isEmpty else { return [:] }
        let obj = try JSONSerialization.jsonObject(with: data)
        return (obj as? [String: Any]) ?? [:]
    }

    static func jsonResponse(_ body: Any, status: FlyingFox.HTTPStatusCode = .ok) -> FlyingFox.HTTPResponse {
        do {
            let data = try JSONSerialization.data(withJSONObject: body, options: [.prettyPrinted])
            return FlyingFox.HTTPResponse(
                statusCode: status,
                headers: [.contentType: "application/json"],
                body: data
            )
        } catch {
            let fallback = "{\"error\":\"\(error.localizedDescription)\"}".data(using: .utf8)!
            return FlyingFox.HTTPResponse(
                statusCode: .internalServerError,
                headers: [.contentType: "application/json"],
                body: fallback
            )
        }
    }
}
