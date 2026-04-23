import Foundation
import SQLite3

// Explicit transient binding helper (SQLite quirks around static strings)
private let SQLITE_TRANSIENT = unsafeBitCast(-1, to: sqlite3_destructor_type.self)

final class MessagesService {
    static let shared = MessagesService()

    private var dbPath: String {
        (NSHomeDirectory() as NSString).appendingPathComponent("Library/Messages/chat.db")
    }

    /// Returns (conversations, optional error string). If FDA isn't granted, error is populated.
    func conversations(limit: Int) -> ([[String: Any]], String?) {
        guard FileManager.default.fileExists(atPath: dbPath) else {
            return ([], "chat.db not found at \(dbPath)")
        }

        var db: OpaquePointer?
        // Open read-only to avoid lock contention with Messages.app
        let flags = SQLITE_OPEN_READONLY | SQLITE_OPEN_NOMUTEX
        let rc = sqlite3_open_v2(dbPath, &db, flags, nil)
        guard rc == SQLITE_OK, let db else {
            let msg = db.flatMap { String(cString: sqlite3_errmsg($0)) } ?? "open failed rc=\(rc)"
            if let db = db { sqlite3_close(db) }
            // rc=14 (SQLITE_CANTOPEN) almost always = FDA not granted
            if rc == SQLITE_CANTOPEN {
                return ([], "Full Disk Access not granted. Open System Settings > Privacy & Security > Full Disk Access and enable JarvisNative.")
            }
            return ([], "sqlite open error: \(msg)")
        }
        defer { sqlite3_close(db) }

        // Apple's chat.db stores dates as nanoseconds since 2001-01-01 UTC (Core Data / Mac epoch)
        // Convert: unix_ts = (date / 1e9) + 978307200
        let sql = """
        SELECT
          c.ROWID as chat_id,
          c.chat_identifier,
          c.display_name,
          c.is_archived,
          (SELECT h.id FROM handle h
             JOIN chat_handle_join chj ON chj.handle_id = h.ROWID
             WHERE chj.chat_id = c.ROWID LIMIT 1) as last_handle,
          (SELECT m.text FROM message m
             JOIN chat_message_join cmj ON cmj.message_id = m.ROWID
             WHERE cmj.chat_id = c.ROWID
             ORDER BY m.date DESC LIMIT 1) as last_text,
          (SELECT m.date FROM message m
             JOIN chat_message_join cmj ON cmj.message_id = m.ROWID
             WHERE cmj.chat_id = c.ROWID
             ORDER BY m.date DESC LIMIT 1) as last_date,
          (SELECT m.is_from_me FROM message m
             JOIN chat_message_join cmj ON cmj.message_id = m.ROWID
             WHERE cmj.chat_id = c.ROWID
             ORDER BY m.date DESC LIMIT 1) as last_from_me
        FROM chat c
        WHERE EXISTS (SELECT 1 FROM chat_message_join WHERE chat_id = c.ROWID)
        ORDER BY last_date DESC
        LIMIT ?;
        """

        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else {
            let msg = String(cString: sqlite3_errmsg(db))
            return ([], "sqlite prepare error: \(msg)")
        }
        defer { sqlite3_finalize(stmt) }

        sqlite3_bind_int(stmt, 1, Int32(limit))

        var out: [[String: Any]] = []
        let iso = ISO8601DateFormatter()
        iso.formatOptions = [.withInternetDateTime]

        while sqlite3_step(stmt) == SQLITE_ROW {
            let chatId = sqlite3_column_int64(stmt, 0)
            let chatIdentifier = stringColumn(stmt, 1) ?? ""
            let displayName = stringColumn(stmt, 2) ?? ""
            let isArchived = sqlite3_column_int(stmt, 3) != 0
            let lastHandle = stringColumn(stmt, 4) ?? ""
            let lastText = stringColumn(stmt, 5) ?? ""
            let lastDateRaw = sqlite3_column_int64(stmt, 6)
            let lastFromMe = sqlite3_column_int(stmt, 7) != 0

            let lastDate: String
            if lastDateRaw > 0 {
                let unix = Double(lastDateRaw) / 1e9 + 978_307_200
                lastDate = iso.string(from: Date(timeIntervalSince1970: unix))
            } else {
                lastDate = ""
            }

            // Resolve to contact name
            let handleForLookup = lastHandle.isEmpty ? chatIdentifier : lastHandle
            let resolvedName = ContactsService.shared.displayName(forHandle: handleForLookup)
            let label = !displayName.isEmpty ? displayName :
                        (resolvedName ?? handleForLookup)

            out.append([
                "chat_id": chatId,
                "chat_identifier": chatIdentifier,
                "display_name": label,
                "raw_handle": handleForLookup,
                "is_archived": isArchived,
                "last_text": lastText,
                "last_date": lastDate,
                "last_from_me": lastFromMe
            ])
        }

        return (out, nil)
    }

    private func stringColumn(_ stmt: OpaquePointer?, _ idx: Int32) -> String? {
        guard let cstr = sqlite3_column_text(stmt, idx) else { return nil }
        return String(cString: cstr)
    }
}
