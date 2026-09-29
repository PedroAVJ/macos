import Contacts
import Darwin
import Dispatch
import Foundation

struct RawContact {
    let contact: CNContact
    let container: CNContainer
}

func jsonPrint(_ object: Any) {
    let data = try! JSONSerialization.data(
        withJSONObject: object,
        options: [.prettyPrinted, .sortedKeys]
    )
    print(String(decoding: data, as: UTF8.self))
}

func fail(_ code: String, _ message: String, status: Int32 = 1) -> Never {
    jsonPrint([
        "ok": false,
        "error": ["code": code, "message": message]
    ])
    exit(status)
}

func authorizationName(_ status: CNAuthorizationStatus) -> String {
    switch status {
    case .notDetermined: return "not_determined"
    case .restricted: return "restricted"
    case .denied: return "denied"
    case .authorized: return "authorized"
    @unknown default: return "unknown"
    }
}

func requireAccess(_ store: CNContactStore) {
    let current = CNContactStore.authorizationStatus(for: .contacts)
    if current == .authorized { return }
    if current == .denied || current == .restricted {
        fail("contacts_access_denied", "macOS has not granted Contacts access")
    }

    let gate = DispatchSemaphore(value: 0)
    var granted = false
    var requestError: Error?
    store.requestAccess(for: .contacts) { allowed, error in
        granted = allowed
        requestError = error
        gate.signal()
    }
    if gate.wait(timeout: .now() + 30) == .timedOut {
        fail("contacts_access_timeout", "Timed out waiting for Contacts access")
    }
    if !granted {
        fail(
            "contacts_access_denied",
            requestError?.localizedDescription ?? "macOS denied Contacts access"
        )
    }
}

func contactKeys() -> [CNKeyDescriptor] {
    [
        CNContactIdentifierKey as CNKeyDescriptor,
        CNContactTypeKey as CNKeyDescriptor,
        CNContactFormatter.descriptorForRequiredKeys(for: .fullName),
        CNContactNamePrefixKey as CNKeyDescriptor,
        CNContactGivenNameKey as CNKeyDescriptor,
        CNContactMiddleNameKey as CNKeyDescriptor,
        CNContactFamilyNameKey as CNKeyDescriptor,
        CNContactPreviousFamilyNameKey as CNKeyDescriptor,
        CNContactNameSuffixKey as CNKeyDescriptor,
        CNContactNicknameKey as CNKeyDescriptor,
        CNContactPhoneticGivenNameKey as CNKeyDescriptor,
        CNContactPhoneticMiddleNameKey as CNKeyDescriptor,
        CNContactPhoneticFamilyNameKey as CNKeyDescriptor,
        CNContactOrganizationNameKey as CNKeyDescriptor,
        CNContactDepartmentNameKey as CNKeyDescriptor,
        CNContactJobTitleKey as CNKeyDescriptor,
        CNContactPhoneNumbersKey as CNKeyDescriptor,
        CNContactEmailAddressesKey as CNKeyDescriptor,
        CNContactPostalAddressesKey as CNKeyDescriptor,
        CNContactUrlAddressesKey as CNKeyDescriptor,
        CNContactInstantMessageAddressesKey as CNKeyDescriptor,
        CNContactSocialProfilesKey as CNKeyDescriptor,
        CNContactBirthdayKey as CNKeyDescriptor,
        CNContactDatesKey as CNKeyDescriptor,
        CNContactRelationsKey as CNKeyDescriptor,
        CNContactImageDataAvailableKey as CNKeyDescriptor
    ]
}

func fetchRawContacts(_ store: CNContactStore) throws -> [RawContact] {
    var result: [RawContact] = []
    for container in try store.containers(matching: nil) {
        let request = CNContactFetchRequest(keysToFetch: contactKeys())
        request.unifyResults = false
        request.predicate = CNContact.predicateForContactsInContainer(
            withIdentifier: container.identifier
        )
        try store.enumerateContacts(with: request) { contact, _ in
            result.append(RawContact(contact: contact, container: container))
        }
    }
    return result
}

func displayName(_ contact: CNContact) -> String {
    CNContactFormatter.string(from: contact, style: .fullName)
        ?? contact.nickname
}

func friendlyLabel(_ label: String?) -> String {
    guard let label, !label.isEmpty else { return "" }
    if label == CNLabelHome { return "home" }
    if label == CNLabelWork { return "work" }
    if label == CNLabelOther { return "other" }
    return label
}

func appleLabel(_ label: String) -> String {
    switch label.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() {
    case "home": return CNLabelHome
    case "work": return CNLabelWork
    case "other": return CNLabelOther
    default: return label
    }
}

func appleRelationshipLabel(_ label: String) -> String {
    switch canonicalLabel(label) {
    case "boss", "manager": return CNLabelContactRelationManager
    default: return label
    }
}

func normalized(_ value: String) -> String {
    value.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
}

func canonicalLabel(_ label: String?) -> String {
    guard let label, !label.isEmpty else { return "" }
    if label == CNLabelHome { return "home" }
    if label == CNLabelWork { return "work" }
    if label == CNLabelOther { return "other" }

    let source: String
    if label.hasPrefix("_$!<"), label.hasSuffix(">!$_") {
        source = String(label.dropFirst(4).dropLast(4))
    } else {
        source = label
    }
    return source
        .replacingOccurrences(
            of: "([a-z0-9])([A-Z])",
            with: "$1_$2",
            options: .regularExpression
        )
        .folding(options: [.diacriticInsensitive, .caseInsensitive], locale: .current)
        .lowercased()
        .replacingOccurrences(
            of: "[^\\p{L}\\p{N}]+",
            with: "_",
            options: .regularExpression
        )
        .trimmingCharacters(in: CharacterSet(charactersIn: "_"))
}

func dateComponentsObject(_ value: DateComponents?) -> Any {
    guard let value else { return NSNull() }
    var result: [String: Any] = [:]
    if let era = value.era { result["era"] = era }
    if let year = value.year { result["year"] = year }
    if let month = value.month { result["month"] = month }
    if let day = value.day { result["day"] = day }
    return result
}

func labeledStringObject(_ entry: CNLabeledValue<NSString>) -> [String: Any] {
    [
        "id": entry.identifier,
        "label": canonicalLabel(entry.label),
        "value": String(entry.value)
    ]
}

func relationObject(_ entry: CNLabeledValue<CNContactRelation>) -> [String: Any] {
    [
        "id": entry.identifier,
        "label": canonicalLabel(entry.label),
        "name": entry.value.name
    ]
}

func addressObject(_ entry: CNLabeledValue<CNPostalAddress>) -> [String: Any] {
    let address = entry.value
    return [
        "id": entry.identifier,
        "label": friendlyLabel(entry.label),
        "street": address.street,
        "city": address.city,
        "state": address.state,
        "postal_code": address.postalCode,
        "country": address.country,
        "country_code": address.isoCountryCode
    ]
}

func defaultPhoneCountryCode() -> String {
    CNContactsUserDefaults.shared().countryCode.uppercased()
}

func defaultPhonePlan(for countryCode: String) -> (callingCode: String, nationalLength: Int)? {
    switch countryCode.uppercased() {
    case "MX": return ("52", 10)
    case "US", "CA": return ("1", 10)
    default: return nil
    }
}

func phoneObject(_ entry: CNLabeledValue<CNPhoneNumber>) -> [String: Any] {
    let raw = entry.value.stringValue
    let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
    let digits = raw.filter(\.isNumber)
    let defaultCountry = defaultPhoneCountryCode()
    let e164: String?
    let source: String

    if trimmed.hasPrefix("+"), !digits.isEmpty {
        if digits.hasPrefix("521"), digits.count == 13 {
            e164 = "+52" + String(digits.dropFirst(3))
            source = "explicit_legacy_mexico"
        } else {
            e164 = "+" + digits
            source = "explicit"
        }
    } else if let plan = defaultPhonePlan(for: defaultCountry),
              digits.count == plan.nationalLength {
        e164 = "+" + plan.callingCode + digits
        source = "default_country"
    } else {
        e164 = nil
        source = "unavailable"
    }
    let e164Object: Any = e164 == nil ? NSNull() : e164!

    return [
        "id": entry.identifier,
        "label": canonicalLabel(entry.label),
        "value": raw,
        "e164": e164Object,
        "e164_source": source,
        "default_country_code": defaultCountry
    ]
}

func contactDataObject(_ contact: CNContact) -> [String: Any] {
    [
        "id": contact.identifier,
        "contact_type": contact.contactType == .organization ? "organization" : "person",
        "name": displayName(contact),
        "name_components": [
            "prefix": contact.namePrefix,
            "given": contact.givenName,
            "middle": contact.middleName,
            "family": contact.familyName,
            "previous_family": contact.previousFamilyName,
            "suffix": contact.nameSuffix,
            "phonetic_given": contact.phoneticGivenName,
            "phonetic_middle": contact.phoneticMiddleName,
            "phonetic_family": contact.phoneticFamilyName
        ],
        "nickname": contact.nickname,
        "organization": contact.organizationName,
        "work": [
            "organization": contact.organizationName,
            "department": contact.departmentName,
            "job_title": contact.jobTitle
        ],
        "phones": contact.phoneNumbers.map(phoneObject),
        "emails": contact.emailAddresses.map(labeledStringObject),
        "addresses": contact.postalAddresses.map(addressObject),
        "urls": contact.urlAddresses.map(labeledStringObject),
        "instant_messages": contact.instantMessageAddresses.map {
            [
                "id": $0.identifier,
                "label": canonicalLabel($0.label),
                "service": $0.value.service,
                "username": $0.value.username
            ]
        },
        "social_profiles": contact.socialProfiles.map {
            [
                "id": $0.identifier,
                "label": canonicalLabel($0.label),
                "service": $0.value.service,
                "username": $0.value.username,
                "user_identifier": $0.value.userIdentifier,
                "url": $0.value.urlString
            ]
        },
        "birthday": dateComponentsObject(contact.birthday),
        "dates": contact.dates.map {
            [
                "id": $0.identifier,
                "label": canonicalLabel($0.label),
                "date": dateComponentsObject($0.value as DateComponents)
            ]
        },
        "relationships": contact.contactRelations.map(relationObject),
        "has_image": contact.imageDataAvailable
    ]
}

func contactObject(_ raw: RawContact) -> [String: Any] {
    var result = contactDataObject(raw.contact)
    result["container"] = [
        "id": raw.container.identifier,
        "name": raw.container.name
    ]
    return result
}

func contactReferenceObject(_ raw: RawContact) -> [String: Any] {
    [
        "id": raw.contact.identifier,
        "name": displayName(raw.contact),
        "nickname": raw.contact.nickname,
        "organization": raw.contact.organizationName,
        "container": [
            "id": raw.container.identifier,
            "name": raw.container.name
        ],
        "relationship_count": raw.contact.contactRelations.count
    ]
}

func relationMatchCandidates(
    _ relation: CNLabeledValue<CNContactRelation>,
    in records: [RawContact]
) -> [[String: Any]] {
    let wanted = normalized(relation.value.name)
    return records.filter { raw in
        let contact = raw.contact
        let candidates = [
            displayName(contact),
            contact.nickname,
            [contact.givenName, contact.familyName]
                .filter { !$0.isEmpty }
                .joined(separator: " ")
        ]
        return candidates.contains { normalized($0) == wanted }
    }.map(contactReferenceObject)
}

func unifiedMeContact(_ store: CNContactStore) -> CNContact {
    do {
        return try store.unifiedMeContactWithKeys(toFetch: contactKeys())
    } catch {
        fail(
            "me_card_unavailable",
            "Contacts did not expose a unified My Card. Set My Card in Contacts or pass an exact raw contact ID to relationships."
        )
    }
}

func parseOptions(_ arguments: [String]) -> ([String], [String: String], Set<String>) {
    var positionals: [String] = []
    var options: [String: String] = [:]
    var flags = Set<String>()
    var index = 0
    while index < arguments.count {
        let value = arguments[index]
        if value.hasPrefix("--") {
            if index + 1 < arguments.count && !arguments[index + 1].hasPrefix("--") {
                options[value] = arguments[index + 1]
                index += 2
            } else {
                flags.insert(value)
                index += 1
            }
        } else {
            positionals.append(value)
            index += 1
        }
    }
    return (positionals, options, flags)
}

func rawContact(withID id: String, in records: [RawContact]) -> RawContact {
    let matches = records.filter { $0.contact.identifier == id }
    if matches.isEmpty {
        fail("contact_not_found", "No raw contact has the requested ID")
    }
    if matches.count > 1 {
        fail("contact_id_ambiguous", "More than one raw contact has the requested ID")
    }
    return matches[0]
}

func sameAddress(
    _ entry: CNLabeledValue<CNPostalAddress>,
    label: String,
    street: String,
    city: String,
    state: String,
    postalCode: String,
    country: String,
    countryCode: String
) -> Bool {
    let address = entry.value
    return friendlyLabel(entry.label) == friendlyLabel(appleLabel(label))
        && normalized(address.street) == normalized(street)
        && normalized(address.city) == normalized(city)
        && normalized(address.state) == normalized(state)
        && normalized(address.postalCode) == normalized(postalCode)
        && normalized(address.country) == normalized(country)
        && normalized(address.isoCountryCode) == normalized(countryCode)
}

func sameRelationship(
    _ entry: CNLabeledValue<CNContactRelation>,
    label: String,
    name: String
) -> Bool {
    canonicalLabel(entry.label) == canonicalLabel(appleRelationshipLabel(label))
        && normalized(entry.value.name) == normalized(name)
}

func validEmail(_ value: String) -> Bool {
    let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
    if trimmed.isEmpty || trimmed.rangeOfCharacter(from: .whitespacesAndNewlines) != nil {
        return false
    }
    let parts = trimmed.split(separator: "@", omittingEmptySubsequences: false)
    return parts.count == 2 && !parts[0].isEmpty && !parts[1].isEmpty
}

func sameEmail(_ entry: CNLabeledValue<NSString>, value: String) -> Bool {
    normalized(String(entry.value)) == normalized(value)
}

var arguments = Array(CommandLine.arguments.dropFirst())
arguments.removeAll { $0 == "--json" }
guard !arguments.isEmpty else {
    fail("usage", "Expected doctor, list, search, read, me, relationships, relationship, email, or address")
}

let store = CNContactStore()
requireAccess(store)

do {
    let command = arguments.removeFirst()

    if command == "doctor" {
        let containers = try store.containers(matching: nil).map {
            ["id": $0.identifier, "name": $0.name]
        }
        jsonPrint([
            "ok": true,
            "data": [
                "authorization": authorizationName(
                    CNContactStore.authorizationStatus(for: .contacts)
                ),
                "containers": containers
            ]
        ])
        exit(0)
    }

    let records = try fetchRawContacts(store)

    if command == "list" {
        let (_, options, _) = parseOptions(arguments)
        let containerFilter = options["--container"].map(normalized)
        let offset = max(0, Int(options["--offset"] ?? "0") ?? 0)
        let requestedLimit = Int(options["--limit"] ?? "100") ?? 100
        let limit = min(max(requestedLimit, 1), 500)
        let filtered = records.filter { raw in
            guard let containerFilter else { return true }
            return normalized(raw.container.name).contains(containerFilter)
        }.sorted {
            let left = normalized(displayName($0.contact))
            let right = normalized(displayName($1.contact))
            return left == right
                ? $0.contact.identifier < $1.contact.identifier
                : left < right
        }
        let page = Array(filtered.dropFirst(offset).prefix(limit))
        let nextOffset = offset + page.count
        let nextOffsetValue: Any = nextOffset < filtered.count ? nextOffset : NSNull()
        jsonPrint([
            "ok": true,
            "data": [
                "contacts": page.map(contactReferenceObject),
                "offset": offset,
                "limit": limit,
                "total": filtered.count,
                "next_offset": nextOffsetValue
            ] as [String: Any]
        ])
        exit(0)
    }

    if command == "search" {
        let (positionals, options, _) = parseOptions(arguments)
        let query = positionals.joined(separator: " ").trimmingCharacters(
            in: .whitespacesAndNewlines
        )
        if query.isEmpty { fail("usage", "search requires a query") }
        let wanted = normalized(query)
        let digits = query.filter(\.isNumber)
        let containerFilter = options["--container"].map(normalized)
        let matches = records.filter { raw in
            if let containerFilter,
               !normalized(raw.container.name).contains(containerFilter) {
                return false
            }
            let values = [
                displayName(raw.contact),
                raw.contact.nickname,
                raw.contact.organizationName
            ] + raw.contact.phoneNumbers.map { $0.value.stringValue }
              + raw.contact.emailAddresses.map { String($0.value) }
              + raw.contact.contactRelations.flatMap {
                  [$0.value.name, canonicalLabel($0.label)]
              }
            let textualMatch = values.contains { normalized($0).contains(wanted) }
            let numberMatch = !digits.isEmpty && raw.contact.phoneNumbers.contains {
                $0.value.stringValue.filter(\.isNumber).hasSuffix(digits)
            }
            return textualMatch || numberMatch
        }
        jsonPrint([
            "ok": true,
            "data": ["contacts": matches.map(contactObject)]
        ])
        exit(0)
    }

    if command == "read" {
        guard arguments.count == 1 else {
            fail("usage", "read requires one raw contact ID")
        }
        jsonPrint([
            "ok": true,
            "data": ["contact": contactObject(rawContact(withID: arguments[0], in: records))]
        ])
        exit(0)
    }

    if command == "me" {
        guard arguments.isEmpty else { fail("usage", "me takes no arguments") }
        let me = unifiedMeContact(store)
        jsonPrint([
            "ok": true,
            "data": ["contact": contactDataObject(me)]
        ])
        exit(0)
    }

    if command == "relationships" {
        guard arguments.count <= 1 else {
            fail("usage", "relationships takes zero arguments for My Card or one raw contact ID")
        }
        let owner: CNContact
        let direction: String
        let ownerObject: [String: Any]
        if let contactID = arguments.first {
            let raw = rawContact(withID: contactID, in: records)
            owner = raw.contact
            ownerObject = contactReferenceObject(raw)
            direction = "outbound_from_selected_card"
        } else {
            owner = unifiedMeContact(store)
            ownerObject = ["id": owner.identifier, "name": displayName(owner)]
            direction = "outbound_from_my_card"
        }
        let relationships = owner.contactRelations.map { relation -> [String: Any] in
            var result = relationObject(relation)
            let matches = relationMatchCandidates(relation, in: records)
            result["matched_contacts"] = matches
            result["match_status"] = matches.isEmpty
                ? "unmatched"
                : (matches.count == 1 ? "exact" : "ambiguous")
            return result
        }
        jsonPrint([
            "ok": true,
            "data": [
                "owner": ownerObject,
                "relationships": relationships,
                "linkage": "name_only",
                "direction": direction
            ]
        ])
        exit(0)
    }

    if command == "relationship" {
        guard !arguments.isEmpty else {
            fail("usage", "relationship requires add")
        }
        let operation = arguments.removeFirst()
        let (positionals, options, _) = parseOptions(arguments)

        if operation == "add" {
            guard positionals.count == 2 else {
                fail(
                    "usage",
                    "relationship add requires owner contact ID and related contact ID"
                )
            }
            guard let label = options["--label"], !label.isEmpty else {
                fail("usage", "relationship add requires --label")
            }

            let owner = rawContact(withID: positionals[0], in: records)
            let related = rawContact(withID: positionals[1], in: records)
            if owner.contact.identifier == related.contact.identifier {
                fail("relationship_self_reference", "A contact cannot be related to itself")
            }

            let relatedName = displayName(related.contact).trimmingCharacters(
                in: .whitespacesAndNewlines
            )
            if relatedName.isEmpty {
                fail(
                    "related_contact_name_missing",
                    "The related contact needs a display name before it can be stored as a relationship"
                )
            }

            if let existing = owner.contact.contactRelations.first(where: {
                sameRelationship($0, label: label, name: relatedName)
            }) {
                jsonPrint([
                    "ok": true,
                    "data": [
                        "status": "already_present",
                        "contact": contactObject(owner),
                        "relationship": relationObject(existing),
                        "related_contact": contactReferenceObject(related)
                    ]
                ])
                exit(0)
            }

            let mutable = owner.contact.mutableCopy() as! CNMutableContact
            mutable.contactRelations.append(
                CNLabeledValue(
                    label: appleRelationshipLabel(label),
                    value: CNContactRelation(name: relatedName)
                )
            )
            let request = CNSaveRequest()
            request.update(mutable)
            try store.execute(request)

            let refreshed = rawContact(
                withID: owner.contact.identifier,
                in: try fetchRawContacts(store)
            )
            guard let saved = refreshed.contact.contactRelations.first(where: {
                sameRelationship($0, label: label, name: relatedName)
            }) else {
                fail(
                    "write_verification_failed",
                    "The saved relationship could not be read back"
                )
            }
            jsonPrint([
                "ok": true,
                "data": [
                    "status": "added",
                    "contact": contactObject(refreshed),
                    "relationship": relationObject(saved),
                    "related_contact": contactReferenceObject(related)
                ]
            ])
            exit(0)
        }

        fail("usage", "relationship requires add")
    }

    if command == "email" {
        guard !arguments.isEmpty else {
            fail("usage", "email requires add")
        }
        let operation = arguments.removeFirst()
        let (positionals, options, _) = parseOptions(arguments)

        if operation == "add" {
            guard positionals.count == 1 else {
                fail("usage", "email add requires one raw contact ID")
            }
            guard let suppliedValue = options["--value"] else {
                fail("usage", "email add requires --value")
            }
            let value = suppliedValue.trimmingCharacters(in: .whitespacesAndNewlines)
            guard validEmail(value) else {
                fail("invalid_email", "The email address must contain one @ and no whitespace")
            }
            let label = options["--label"] ?? "home"
            let raw = rawContact(withID: positionals[0], in: records)

            if let existing = raw.contact.emailAddresses.first(where: {
                sameEmail($0, value: value)
            }) {
                jsonPrint([
                    "ok": true,
                    "data": [
                        "status": "already_present",
                        "contact": contactObject(raw),
                        "email": labeledStringObject(existing)
                    ]
                ])
                exit(0)
            }

            let mutable = raw.contact.mutableCopy() as! CNMutableContact
            mutable.emailAddresses.append(
                CNLabeledValue(label: appleLabel(label), value: value as NSString)
            )
            let request = CNSaveRequest()
            request.update(mutable)
            try store.execute(request)

            let refreshed = rawContact(
                withID: raw.contact.identifier,
                in: try fetchRawContacts(store)
            )
            guard let saved = refreshed.contact.emailAddresses.first(where: {
                sameEmail($0, value: value)
            }) else {
                fail("write_verification_failed", "The saved email address could not be read back")
            }
            jsonPrint([
                "ok": true,
                "data": [
                    "status": "added",
                    "contact": contactObject(refreshed),
                    "email": labeledStringObject(saved)
                ]
            ])
            exit(0)
        }

        fail("usage", "email requires add")
    }

    if command == "address" {
        guard !arguments.isEmpty else {
            fail("usage", "address requires add or remove")
        }
        let operation = arguments.removeFirst()
        let (positionals, options, flags) = parseOptions(arguments)

        if operation == "add" {
            guard positionals.count == 1 else {
                fail("usage", "address add requires one raw contact ID")
            }
            guard let street = options["--street"], !street.isEmpty,
                  let city = options["--city"], !city.isEmpty,
                  let state = options["--state"], !state.isEmpty,
                  let country = options["--country"], !country.isEmpty,
                  let countryCode = options["--country-code"], !countryCode.isEmpty else {
                fail(
                    "usage",
                    "address add requires street, city, state, country, and country-code"
                )
            }
            let label = options["--label"] ?? "home"
            let postalCode = options["--postal-code"] ?? ""
            let raw = rawContact(withID: positionals[0], in: records)

            if let existing = raw.contact.postalAddresses.first(where: {
                sameAddress(
                    $0,
                    label: label,
                    street: street,
                    city: city,
                    state: state,
                    postalCode: postalCode,
                    country: country,
                    countryCode: countryCode
                )
            }) {
                jsonPrint([
                    "ok": true,
                    "data": [
                        "status": "already_present",
                        "contact": contactObject(raw),
                        "address": addressObject(existing)
                    ]
                ])
                exit(0)
            }

            let canonicalLabel = friendlyLabel(appleLabel(label))
            if raw.contact.postalAddresses.contains(where: {
                friendlyLabel($0.label) == canonicalLabel
            }) {
                fail(
                    "address_label_conflict",
                    "The contact already has a different address with that label"
                )
            }

            let postalAddress = CNMutablePostalAddress()
            postalAddress.street = street
            postalAddress.city = city
            postalAddress.state = state
            postalAddress.postalCode = postalCode
            postalAddress.country = country
            postalAddress.isoCountryCode = countryCode.uppercased()

            let mutable = raw.contact.mutableCopy() as! CNMutableContact
            mutable.postalAddresses.append(
                CNLabeledValue(label: appleLabel(label), value: postalAddress.copy() as! CNPostalAddress)
            )
            let request = CNSaveRequest()
            request.update(mutable)
            try store.execute(request)

            let refreshed = rawContact(withID: raw.contact.identifier, in: try fetchRawContacts(store))
            guard let saved = refreshed.contact.postalAddresses.first(where: {
                sameAddress(
                    $0,
                    label: label,
                    street: street,
                    city: city,
                    state: state,
                    postalCode: postalCode,
                    country: country,
                    countryCode: countryCode
                )
            }) else {
                fail("write_verification_failed", "The saved address could not be read back")
            }
            jsonPrint([
                "ok": true,
                "data": [
                    "status": "added",
                    "contact": contactObject(refreshed),
                    "address": addressObject(saved)
                ]
            ])
            exit(0)
        }

        if operation == "remove" {
            guard positionals.count == 2 else {
                fail("usage", "address remove requires contact ID and address ID")
            }
            guard flags.contains("--confirm") else {
                fail("confirmation_required", "address remove requires --confirm")
            }
            let raw = rawContact(withID: positionals[0], in: records)
            let addressID = positionals[1]
            guard raw.contact.postalAddresses.contains(where: { $0.identifier == addressID }) else {
                fail("address_not_found", "No address on the contact has the requested ID")
            }
            let mutable = raw.contact.mutableCopy() as! CNMutableContact
            mutable.postalAddresses.removeAll { $0.identifier == addressID }
            let request = CNSaveRequest()
            request.update(mutable)
            try store.execute(request)

            let refreshed = rawContact(withID: raw.contact.identifier, in: try fetchRawContacts(store))
            if refreshed.contact.postalAddresses.contains(where: { $0.identifier == addressID }) {
                fail("write_verification_failed", "The removed address is still present")
            }
            jsonPrint([
                "ok": true,
                "data": [
                    "status": "removed",
                    "contact": contactObject(refreshed),
                    "removed_address_id": addressID
                ]
            ])
            exit(0)
        }

        fail("usage", "address requires add or remove")
    }

    fail("usage", "Unknown command: \(command)")
} catch {
    fail("contacts_error", error.localizedDescription)
}
