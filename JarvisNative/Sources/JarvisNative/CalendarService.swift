import Foundation
import EventKit

final class CalendarService {
    static let shared = CalendarService()
    private let store = EKEventStore()

    private var iso: ISO8601DateFormatter {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f
    }

    func requestAccess(completion: @escaping (Bool) -> Void) {
        if #available(macOS 14.0, *) {
            store.requestFullAccessToEvents { granted, error in
                if let error = error { NSLog("Calendar request error: \(error)") }
                completion(granted)
            }
        } else {
            store.requestAccess(to: .event) { granted, error in
                if let error = error { NSLog("Calendar request error: \(error)") }
                completion(granted)
            }
        }
    }

    /// Returns events from all calendars spanning `daysAhead` days from now.
    func events(daysAhead: Int) async -> [[String: Any]] {
        let status: EKAuthorizationStatus = EKEventStore.authorizationStatus(for: .event)
        if #available(macOS 14.0, *) {
            guard status == .fullAccess || status == .writeOnly else {
                NSLog("Calendar not authorized (status=\(status.rawValue))")
                return []
            }
        } else {
            guard status == .authorized else {
                NSLog("Calendar not authorized (status=\(status.rawValue))")
                return []
            }
        }

        let start = Date()
        let end = Calendar.current.date(byAdding: .day, value: daysAhead, to: start) ?? start
        let calendars = store.calendars(for: .event)
        let predicate = store.predicateForEvents(withStart: start, end: end, calendars: calendars)
        let events = store.events(matching: predicate)

        let iso = self.iso
        let sensitiveCalendars: Set<String> = ["Rotation", "Subscribed Calendar", "Work"]
        return events.map { ev -> [String: Any] in
            let calendarTitle = ev.calendar?.title ?? ""
            let isSensitive = sensitiveCalendars.contains(calendarTitle)
            let displayTitle: String = isSensitive ? "(hidden)" : (ev.title ?? "")
            return [
                "title": displayTitle,
                "start": iso.string(from: ev.startDate),
                "end": iso.string(from: ev.endDate),
                "calendar": calendarTitle,
                "location": ev.location ?? "",
                "notes": "",          // HIPAA: never return clinical notes
                "all_day": ev.isAllDay,
                "id": ev.eventIdentifier ?? ""
            ]
        }
    }
}
