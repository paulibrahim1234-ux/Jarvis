import Foundation
import Contacts

final class ContactsService {
    static let shared = ContactsService()
    private let store = CNContactStore()

    func requestAccess(completion: @escaping (Bool) -> Void) {
        store.requestAccess(for: .contacts) { granted, error in
            if let error = error { NSLog("Contacts request error: \(error)") }
            completion(granted)
        }
    }

    func search(query: String) async -> [[String: Any]] {
        let q = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !q.isEmpty else { return [] }

        let status = CNContactStore.authorizationStatus(for: .contacts)
        guard status == .authorized else {
            NSLog("Contacts not authorized (status=\(status.rawValue))")
            return []
        }

        let keys: [CNKeyDescriptor] = [
            CNContactGivenNameKey as CNKeyDescriptor,
            CNContactFamilyNameKey as CNKeyDescriptor,
            CNContactOrganizationNameKey as CNKeyDescriptor,
            CNContactPhoneNumbersKey as CNKeyDescriptor,
            CNContactEmailAddressesKey as CNKeyDescriptor
        ]

        let predicate = CNContact.predicateForContacts(matchingName: q)

        do {
            let results = try store.unifiedContacts(matching: predicate, keysToFetch: keys)
            return results.map { c -> [String: Any] in
                let phones = c.phoneNumbers.map { ["label": CNLabeledValue<CNPhoneNumber>.localizedString(forLabel: $0.label ?? ""), "number": $0.value.stringValue] }
                let emails = c.emailAddresses.map { ["label": CNLabeledValue<NSString>.localizedString(forLabel: $0.label ?? ""), "email": ($0.value as String)] }
                return [
                    "given_name": c.givenName,
                    "family_name": c.familyName,
                    "organization": c.organizationName,
                    "phones": phones,
                    "emails": emails
                ]
            }
        } catch {
            NSLog("Contacts fetch error: \(error)")
            return []
        }
    }

    /// Resolve a handle (phone number or email) to a display name.
    /// Used by MessagesService to label conversations.
    func displayName(forHandle handle: String) -> String? {
        let status = CNContactStore.authorizationStatus(for: .contacts)
        guard status == .authorized else { return nil }

        let keys: [CNKeyDescriptor] = [
            CNContactGivenNameKey as CNKeyDescriptor,
            CNContactFamilyNameKey as CNKeyDescriptor,
            CNContactPhoneNumbersKey as CNKeyDescriptor,
            CNContactEmailAddressesKey as CNKeyDescriptor
        ]

        // Email-ish?
        if handle.contains("@") {
            let predicate = CNContact.predicateForContacts(matchingEmailAddress: handle)
            if let c = try? store.unifiedContacts(matching: predicate, keysToFetch: keys).first {
                return Self.fullName(c)
            }
        } else {
            // Phone: strip non-digits for matching
            let digits = handle.filter { $0.isNumber || $0 == "+" }
            let predicate = CNContact.predicateForContacts(matching: CNPhoneNumber(stringValue: digits))
            if let c = try? store.unifiedContacts(matching: predicate, keysToFetch: keys).first {
                return Self.fullName(c)
            }
        }
        return nil
    }

    private static func fullName(_ c: CNContact) -> String {
        let parts = [c.givenName, c.familyName].filter { !$0.isEmpty }
        if parts.isEmpty { return c.organizationName }
        return parts.joined(separator: " ")
    }
}
