import AppKit
import ApplicationServices
import Foundation
import Security

private let brokerVersion = "1.0.0"
private let keychainService = "com.pedroavj.macbook.credential-broker"
private let macLoginAccount = "macos-login"

#if BROKER_SELF_TEST_BUILD
private let brokerSelfTestBuild = true
#else
private let brokerSelfTestBuild = false
#endif

private enum BrokerError: Error, CustomStringConvertible {
    case message(String)

    var description: String {
        switch self {
        case .message(let message): return message
        }
    }
}

private func securityMessage(_ status: OSStatus) -> String {
    (SecCopyErrorMessageString(status, nil) as String?) ?? "OSStatus \(status)"
}

private enum CodeIdentity {
    static let approvedHostRequirement = """
    (anchor apple generic and certificate leaf[subject.OU] = "2DC432GLL2" and identifier "codex") or
    (anchor apple generic and certificate leaf[subject.OU] = "Q6L2SF6YDW" and identifier "com.anthropic.claude-code")
    """

    static func process(_ pid: pid_t, satisfies requirementText: String) -> Bool {
        let attributes = [
            kSecGuestAttributePid as String: NSNumber(value: pid)
        ] as CFDictionary
        var code: SecCode?
        guard SecCodeCopyGuestWithAttributes(nil, attributes, [], &code) == errSecSuccess,
              let code else {
            return false
        }

        var requirement: SecRequirement?
        guard SecRequirementCreateWithString(
            requirementText as CFString,
            [],
            &requirement
        ) == errSecSuccess, let requirement else {
            return false
        }

        return SecCodeCheckValidity(
            code,
            SecCSFlags(rawValue: kSecCSStrictValidate),
            requirement
        ) == errSecSuccess
    }

    static func parentIsApprovedHost() -> Bool {
        process(getppid(), satisfies: approvedHostRequirement)
    }

    static func targetIsApproved(pid: pid_t, bundleIdentifier: String) -> Bool {
        let requirement: String
        switch bundleIdentifier {
        case "com.google.Chrome":
            requirement = "anchor apple generic and certificate leaf[subject.OU] = \"EQHXZ8M8AV\" and identifier \"com.google.Chrome\""
        case "com.apple.coreservices.uiagent",
             "com.apple.systempreferences",
             "com.apple.Passwords",
             "com.apple.SecurityAgent":
            requirement = "anchor apple and identifier \"\(bundleIdentifier)\""
        default:
            return false
        }
        return process(pid, satisfies: requirement)
    }
}

private struct TargetSnapshot {
    let element: AXUIElement
    let pid: pid_t
    let bundleIdentifier: String
    let applicationName: String
    let windowTitle: String
    let role: String
    let subrole: String
    let ancestry: [String]
    let containsWebArea: Bool
    let isDialogLike: Bool
    let isSecureField: Bool

    var fingerprint: String {
        [
            String(pid),
            bundleIdentifier,
            windowTitle,
            role,
            subrole,
            ancestry.joined(separator: ">")
        ].joined(separator: "|")
    }

    var publicDictionary: [String: Any] {
        [
            "application": applicationName,
            "bundleIdentifier": bundleIdentifier,
            "windowTitle": windowTitle,
            "role": role,
            "subrole": subrole,
            "containsWebArea": containsWebArea,
            "dialogLike": isDialogLike,
            "secureField": isSecureField
        ]
    }
}

private enum TargetInspector {
    private static func copyAttribute(
        _ element: AXUIElement,
        _ attribute: String
    ) -> CFTypeRef? {
        var value: CFTypeRef?
        guard AXUIElementCopyAttributeValue(
            element,
            attribute as CFString,
            &value
        ) == .success else {
            return nil
        }
        return value
    }

    private static func stringAttribute(
        _ element: AXUIElement,
        _ attribute: String
    ) -> String {
        copyAttribute(element, attribute) as? String ?? ""
    }

    private static func elementAttribute(
        _ element: AXUIElement,
        _ attribute: String
    ) -> AXUIElement? {
        guard let value = copyAttribute(element, attribute),
              CFGetTypeID(value) == AXUIElementGetTypeID() else {
            return nil
        }
        return unsafeBitCast(value, to: AXUIElement.self)
    }

    static func capture() throws -> TargetSnapshot {
        guard AXIsProcessTrusted() else {
            throw BrokerError.message("Accessibility access is not available to the credential broker.")
        }

        let systemWide = AXUIElementCreateSystemWide()
        guard let focused = elementAttribute(systemWide, kAXFocusedUIElementAttribute) else {
            throw BrokerError.message("No focused accessibility element is available.")
        }

        var pid: pid_t = 0
        guard AXUIElementGetPid(focused, &pid) == .success, pid > 0 else {
            throw BrokerError.message("The focused element has no verifiable owning process.")
        }

        let running = NSRunningApplication(processIdentifier: pid)
        let bundleIdentifier = running?.bundleIdentifier ?? ""
        let applicationName = running?.localizedName ?? bundleIdentifier
        let role = stringAttribute(focused, kAXRoleAttribute)
        let subrole = stringAttribute(focused, kAXSubroleAttribute)

        var ancestry: [String] = []
        var containsWebArea = false
        var isDialogLike = false
        var current: AXUIElement? = focused
        var windowTitle = ""

        for _ in 0..<16 {
            guard let element = current else { break }
            let ancestorRole = stringAttribute(element, kAXRoleAttribute)
            let ancestorSubrole = stringAttribute(element, kAXSubroleAttribute)
            let marker = ancestorSubrole.isEmpty
                ? ancestorRole
                : "\(ancestorRole):\(ancestorSubrole)"
            if !marker.isEmpty { ancestry.append(marker) }

            if ancestorRole == "AXWebArea" {
                containsWebArea = true
            }
            if ancestorRole == (kAXSheetRole as String)
                || ancestorSubrole == (kAXDialogSubrole as String)
                || ancestorRole == "AXDialog"
                || ancestorSubrole == "AXSystemDialog" {
                isDialogLike = true
            }
            if windowTitle.isEmpty,
               ancestorRole == (kAXWindowRole as String) {
                windowTitle = stringAttribute(element, kAXTitleAttribute)
            }
            current = elementAttribute(element, kAXParentAttribute)
        }

        if windowTitle.isEmpty,
           let window = elementAttribute(focused, kAXWindowAttribute) {
            windowTitle = stringAttribute(window, kAXTitleAttribute)
            let windowSubrole = stringAttribute(window, kAXSubroleAttribute)
            if windowSubrole == (kAXDialogSubrole as String)
                || windowSubrole == "AXSystemDialog" {
                isDialogLike = true
            }
        }

        return TargetSnapshot(
            element: focused,
            pid: pid,
            bundleIdentifier: bundleIdentifier,
            applicationName: applicationName,
            windowTitle: windowTitle,
            role: role,
            subrole: subrole,
            ancestry: ancestry,
            containsWebArea: containsWebArea,
            isDialogLike: isDialogLike,
            isSecureField: subrole == (kAXSecureTextFieldSubrole as String)
        )
    }

    static func supportReason(for target: TargetSnapshot) -> String? {
        guard target.isSecureField else {
            return "The focused element is not an accessibility-protected secure text field."
        }
        guard !target.containsWebArea else {
            return "Web-page password fields are deliberately excluded from the Mac login credential."
        }
        guard target.isDialogLike else {
            return "The secure field is not inside a native dialog or sheet."
        }
        guard CodeIdentity.targetIsApproved(
            pid: target.pid,
            bundleIdentifier: target.bundleIdentifier
        ) else {
            return "The owning application is not on the signed target allowlist."
        }
        return nil
    }
}

private enum KeychainStore {
    private static func baseQuery(account: String) -> [CFString: Any] {
        [
            kSecClass: kSecClassGenericPassword,
            kSecAttrService: keychainService,
            kSecAttrAccount: account,
            kSecAttrSynchronizable: false
        ]
    }

    private static func brokerAccess(account: String) throws -> SecAccess {
        var trustedApplication: SecTrustedApplication?
        let trustedStatus = SecTrustedApplicationCreateFromPath(
            nil,
            &trustedApplication
        )
        guard trustedStatus == errSecSuccess, let trustedApplication else {
            throw BrokerError.message(
                "Could not create the broker Keychain identity: \(securityMessage(trustedStatus))"
            )
        }

        var access: SecAccess?
        let accessStatus = SecAccessCreate(
            "MacBook Credential Broker: \(account)" as CFString,
            [trustedApplication] as CFArray,
            &access
        )
        guard accessStatus == errSecSuccess, let access else {
            throw BrokerError.message(
                "Could not create the Keychain access policy: \(securityMessage(accessStatus))"
            )
        }
        return access
    }

    static func status(account: String) throws -> Bool {
        var query = baseQuery(account: account)
        query[kSecMatchLimit] = kSecMatchLimitOne
        query[kSecReturnAttributes] = true
        var result: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        switch status {
        case errSecSuccess: return true
        case errSecItemNotFound: return false
        default:
            throw BrokerError.message(
                "Could not inspect the credential item: \(securityMessage(status))"
            )
        }
    }

    static func read(account: String) throws -> Data {
        var query = baseQuery(account: account)
        query[kSecMatchLimit] = kSecMatchLimitOne
        query[kSecReturnData] = true
        var result: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        guard status == errSecSuccess, let data = result as? Data else {
            throw BrokerError.message(
                status == errSecItemNotFound
                    ? "The credential is not configured."
                    : "Keychain refused the credential request: \(securityMessage(status))"
            )
        }
        return data
    }

    static func save(account: String, data: Data, label: String) throws {
        let access = try brokerAccess(account: account)
        var add = baseQuery(account: account)
        add[kSecAttrLabel] = label
        add[kSecAttrDescription] = "One-time, human-approved credential fill"
        add[kSecAttrAccess] = access
        add[kSecValueData] = data

        let status = SecItemAdd(add as CFDictionary, nil)
        if status == errSecDuplicateItem {
            let update: [CFString: Any] = [
                kSecValueData: data,
                kSecAttrAccess: access,
                kSecAttrLabel: label,
                kSecAttrDescription: "One-time, human-approved credential fill"
            ]
            let updateStatus = SecItemUpdate(
                baseQuery(account: account) as CFDictionary,
                update as CFDictionary
            )
            guard updateStatus == errSecSuccess else {
                throw BrokerError.message(
                    "Could not update the credential item: \(securityMessage(updateStatus))"
                )
            }
        } else if status != errSecSuccess {
            throw BrokerError.message(
                "Could not create the credential item: \(securityMessage(status))"
            )
        }
    }

    static func delete(account: String) {
        SecItemDelete(baseQuery(account: account) as CFDictionary)
    }

}

private enum CredentialInjector {
    static func fill(_ data: Data, into target: TargetSnapshot) throws -> String {
        guard let secret = String(data: data, encoding: .utf8), !secret.isEmpty else {
            throw BrokerError.message("The stored credential is empty or not valid UTF-8.")
        }

        let setStatus: AXError = DispatchQueue.main.sync {
            AXUIElementSetAttributeValue(
                target.element,
                kAXValueAttribute as CFString,
                secret as CFString
            )
        }
        if setStatus == .success {
            return "accessibility-value"
        }

        let units = Array(secret.utf16)
        guard !units.isEmpty else {
            throw BrokerError.message("The stored credential is empty.")
        }
        guard let source = CGEventSource(stateID: .hidSystemState) else {
            throw BrokerError.message("Could not create a protected keyboard event source.")
        }

        for chunkStart in stride(from: 0, to: units.count, by: 20) {
            let chunkEnd = min(chunkStart + 20, units.count)
            let chunk = Array(units[chunkStart..<chunkEnd])
            guard let down = CGEvent(
                keyboardEventSource: source,
                virtualKey: 0,
                keyDown: true
            ), let up = CGEvent(
                keyboardEventSource: source,
                virtualKey: 0,
                keyDown: false
            ) else {
                throw BrokerError.message("Could not create protected keyboard events.")
            }
            chunk.withUnsafeBufferPointer { pointer in
                down.keyboardSetUnicodeString(
                    stringLength: pointer.count,
                    unicodeString: pointer.baseAddress
                )
                up.keyboardSetUnicodeString(
                    stringLength: pointer.count,
                    unicodeString: pointer.baseAddress
                )
            }
            down.post(tap: .cghidEventTap)
            up.post(tap: .cghidEventTap)
        }
        return "protected-key-events"
    }
}

private final class PendingResponse {
    private let condition = NSCondition()
    private var response: [String: Any]?

    func fulfill(_ response: [String: Any]) {
        condition.lock()
        self.response = response
        condition.broadcast()
        condition.unlock()
    }

    func wait(timeout: TimeInterval) -> [String: Any]? {
        condition.lock()
        defer { condition.unlock() }
        let deadline = Date(timeIntervalSinceNow: timeout)
        while response == nil, condition.wait(until: deadline) {
            // Re-check after every wake; a wake without a response is not approval.
        }
        return response
    }
}

private final class JSONRPCWriter {
    private let lock = NSLock()

    func send(_ object: [String: Any]) {
        guard JSONSerialization.isValidJSONObject(object),
              let data = try? JSONSerialization.data(withJSONObject: object),
              var line = String(data: data, encoding: .utf8) else {
            return
        }
        line.append("\n")
        lock.lock()
        FileHandle.standardOutput.write(Data(line.utf8))
        lock.unlock()
    }
}

private final class SelfTestWindow {
    let window: NSWindow
    let field: NSSecureTextField

    init() {
        window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 460, height: 180),
            styleMask: [.titled, .closable],
            backing: .buffered,
            defer: false
        )
        window.title = "MacBook Credential Broker — Synthetic Test"
        window.center()

        let label = NSTextField(labelWithString: "Synthetic secret target (no real credential)")
        label.font = .systemFont(ofSize: 14, weight: .medium)
        field = NSSecureTextField(frame: .zero)
        field.placeholderString = "Waiting for approved synthetic fill"
        field.isEditable = true
        field.isSelectable = true

        let stack = NSStackView(views: [label, field])
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = 16
        stack.translatesAutoresizingMaskIntoConstraints = false
        field.translatesAutoresizingMaskIntoConstraints = false

        let content = NSView()
        content.addSubview(stack)
        window.contentView = content
        NSLayoutConstraint.activate([
            stack.leadingAnchor.constraint(equalTo: content.leadingAnchor, constant: 28),
            stack.trailingAnchor.constraint(equalTo: content.trailingAnchor, constant: -28),
            stack.centerYAnchor.constraint(equalTo: content.centerYAnchor),
            field.widthAnchor.constraint(equalTo: stack.widthAnchor),
            field.heightAnchor.constraint(equalToConstant: 28)
        ])
    }

    func showAndFocus() {
        NSApp.activate(ignoringOtherApps: true)
        window.makeKeyAndOrderFront(nil)
        window.makeFirstResponder(field)
    }

    func close() {
        field.stringValue = ""
        window.orderOut(nil)
        window.close()
    }
}

private final class BrokerServer {
    private let writer = JSONRPCWriter()
    private let pendingLock = NSLock()
    private var pending: [String: PendingResponse] = [:]
    private let credentialOperationLock = NSLock()
    private let trustedHost = CodeIdentity.parentIsApprovedHost()

    private static let tools: [[String: Any]] = [
        [
            "name": "credential_status",
            "title": "Credential Status",
            "description": "Check whether the fixed Mac login credential alias is configured. Returns presence only and can never return secret data.",
            "inputSchema": ["type": "object", "properties": [:]],
            "annotations": [
                "readOnlyHint": true,
                "destructiveHint": false,
                "openWorldHint": false,
                "idempotentHint": true
            ]
        ],
        [
            "name": "inspect_credential_target",
            "title": "Inspect Credential Target",
            "description": "Inspect the focused accessibility role, signed application identity, and native-dialog safety checks without reading any field value.",
            "inputSchema": ["type": "object", "properties": [:]],
            "annotations": [
                "readOnlyHint": true,
                "destructiveHint": false,
                "openWorldHint": false,
                "idempotentHint": true
            ]
        ],
        [
            "name": "authorize_and_fill_credential",
            "title": "Approve and Fill Mac Login Password",
            "description": "Request one-time human approval in the current thread, re-verify the focused signed native secure dialog, and fill the Mac login password without returning it. Never presses Return.",
            "inputSchema": [
                "type": "object",
                "properties": [
                    "credential": [
                        "type": "string",
                        "enum": [macLoginAccount],
                        "description": "The fixed non-secret credential alias."
                    ],
                    "purpose": [
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 240,
                        "description": "A concise explanation shown to the human approver. Never include a secret."
                    ]
                ],
                "required": ["credential", "purpose"],
                "additionalProperties": false
            ],
            "annotations": [
                "readOnlyHint": false,
                "destructiveHint": false,
                "openWorldHint": false,
                "idempotentHint": false
            ]
        ],
        [
            "name": "test_credential_approval_channel",
            "title": "Test Credential Approval Channel",
            "description": "Present a no-secret, no-action approval card to verify that MCP elicitation reaches the current client.",
            "inputSchema": ["type": "object", "properties": [:]],
            "annotations": [
                "readOnlyHint": true,
                "destructiveHint": false,
                "openWorldHint": false,
                "idempotentHint": false
            ]
        ],
        [
            "name": "run_credential_broker_self_test",
            "title": "Run Credential Broker Self-Test",
            "description": "With human approval, create a temporary synthetic Keychain item, fill it into a broker-owned secure field through the production injection path, verify it internally, and delete it. Never uses or reveals a real credential.",
            "inputSchema": ["type": "object", "properties": [:]],
            "annotations": [
                "readOnlyHint": false,
                "destructiveHint": false,
                "openWorldHint": false,
                "idempotentHint": false
            ]
        ]
    ]

    private func idKey(_ value: Any) -> String {
        if let string = value as? String { return "s:\(string)" }
        if let number = value as? NSNumber { return "n:\(number.stringValue)" }
        return "u:\(String(describing: value))"
    }

    private func sendResult(id: Any, result: [String: Any]) {
        writer.send(["jsonrpc": "2.0", "id": id, "result": result])
    }

    private func sendError(id: Any, code: Int, message: String) {
        writer.send([
            "jsonrpc": "2.0",
            "id": id,
            "error": ["code": code, "message": message]
        ])
    }

    private func toolResult(
        _ text: String,
        structured: [String: Any],
        isError: Bool = false
    ) -> [String: Any] {
        var result: [String: Any] = [
            "content": [["type": "text", "text": text]],
            "structuredContent": structured
        ]
        if isError { result["isError"] = true }
        return result
    }

    private func requestApproval(message: String, fieldTitle: String) -> Bool {
        let requestID = "broker-elicitation-\(UUID().uuidString)"
        let response = PendingResponse()
        let key = idKey(requestID)
        pendingLock.lock()
        pending[key] = response
        pendingLock.unlock()
        defer {
            pendingLock.lock()
            pending.removeValue(forKey: key)
            pendingLock.unlock()
        }

        writer.send([
            "jsonrpc": "2.0",
            "id": requestID,
            "method": "elicitation/create",
            "params": [
                "mode": "form",
                "message": message,
                "requestedSchema": [
                    "type": "object",
                    "properties": [
                        "approve": [
                            "type": "boolean",
                            "title": fieldTitle,
                            "description": "This approval is valid for this request only.",
                            "default": false
                        ]
                    ],
                    "required": ["approve"]
                ]
            ]
        ])

        guard let envelope = response.wait(timeout: 600),
              let result = envelope["result"] as? [String: Any],
              result["action"] as? String == "accept",
              let content = result["content"] as? [String: Any],
              content["approve"] as? Bool == true else {
            return false
        }
        return true
    }

    private func handleTool(name: String, arguments: [String: Any]) -> [String: Any] {
        do {
            switch name {
            case "credential_status":
                let configured = try KeychainStore.status(account: macLoginAccount)
                return toolResult(
                    configured
                        ? "The Mac login credential alias is configured. No secret data was read."
                        : "The Mac login credential alias is not configured. No secret data was read.",
                    structured: [
                        "credential": macLoginAccount,
                        "configured": configured,
                        "secretReturned": false
                    ]
                )

            case "inspect_credential_target":
                let target = try TargetInspector.capture()
                let reason = TargetInspector.supportReason(for: target)
                var structured = target.publicDictionary
                structured["supported"] = reason == nil
                structured["secretRead"] = false
                if let reason { structured["reason"] = reason }
                let targetMessage = reason == nil
                    ? "The focused element is a supported signed native secure-dialog target. No field value was read."
                    : "The focused element is not an approved credential target: \(reason ?? "unknown reason") No field value was read."
                return toolResult(
                    targetMessage,
                    structured: structured,
                    isError: false
                )

            case "test_credential_approval_channel":
                let approved = requestApproval(
                    message: "No-secret MacBook credential approval test. Approving only proves that this thread can pause and resume an MCP request. It will not read Keychain, type text, or perform an external action.",
                    fieldTitle: "Approve no-action test"
                )
                return toolResult(
                    approved
                        ? "The approval channel test passed. No secret was requested and no external action occurred."
                        : "The approval channel test ended without approval. No action occurred.",
                    structured: [
                        "approved": approved,
                        "secretRead": false,
                        "externalActionPerformed": false
                    ]
                )

            case "authorize_and_fill_credential":
                return try authorizeAndFill(arguments: arguments)

            case "run_credential_broker_self_test":
                return try runSelfTest()

            default:
                return toolResult(
                    "Unknown credential broker tool.",
                    structured: ["unknownTool": name],
                    isError: true
                )
            }
        } catch {
            return toolResult(
                "Credential broker stopped safely: \(error)",
                structured: [
                    "completed": false,
                    "secretReturned": false,
                    "error": String(describing: error)
                ],
                isError: true
            )
        }
    }

    private func authorizeAndFill(arguments: [String: Any]) throws -> [String: Any] {
        credentialOperationLock.lock()
        defer { credentialOperationLock.unlock() }

        guard trustedHost else {
            throw BrokerError.message(
                "Sensitive operations are accepted only when this signed broker is launched directly by the signed Codex or Claude host."
            )
        }
        guard arguments["credential"] as? String == macLoginAccount else {
            throw BrokerError.message("Only the fixed macos-login credential alias is supported.")
        }
        guard let rawPurpose = arguments["purpose"] as? String else {
            throw BrokerError.message("A purpose is required for human approval.")
        }
        let purpose = rawPurpose
            .replacingOccurrences(of: "\n", with: " ")
            .replacingOccurrences(of: "\r", with: " ")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        guard !purpose.isEmpty, purpose.count <= 240 else {
            throw BrokerError.message("The approval purpose must contain 1 to 240 characters.")
        }
        guard try KeychainStore.status(account: macLoginAccount) else {
            throw BrokerError.message(
                "The macos-login credential is not configured. Use the broker's native provisioning dialog; never paste the password into chat or a shell command."
            )
        }

        let before = try TargetInspector.capture()
        if let reason = TargetInspector.supportReason(for: before) {
            throw BrokerError.message(reason)
        }
        let targetSummary = [
            before.applicationName,
            before.bundleIdentifier,
            before.windowTitle.isEmpty ? "untitled native dialog" : before.windowTitle
        ].joined(separator: " — ")
        let approved = requestApproval(
            message: "Allow one-time use of the Mac login password for: \(purpose)\n\nVerified target: \(targetSummary)\n\nThe broker will fill only this native secure field. It will not return, copy, display, log, or submit the password.",
            fieldTitle: "Approve one-time password fill"
        )
        guard approved else {
            return toolResult(
                "Credential fill was not approved. No secret was read and no field was changed.",
                structured: [
                    "approved": false,
                    "filled": false,
                    "secretReturned": false,
                    "submitted": false
                ]
            )
        }

        _ = DispatchQueue.main.sync {
            NSRunningApplication(processIdentifier: before.pid)?.activate()
        }
        Thread.sleep(forTimeInterval: 0.2)
        let after = try TargetInspector.capture()
        guard after.fingerprint == before.fingerprint else {
            throw BrokerError.message(
                "The focused target changed after approval, so the credential was not read or filled."
            )
        }
        if let reason = TargetInspector.supportReason(for: after) {
            throw BrokerError.message(reason)
        }

        var secret = try KeychainStore.read(account: macLoginAccount)
        defer { secret.resetBytes(in: 0..<secret.count) }
        let method = try CredentialInjector.fill(secret, into: after)

        return toolResult(
            "The approved Mac login password was filled into the verified native secure field. It was not returned or submitted.",
            structured: [
                "approved": true,
                "filled": true,
                "secretReturned": false,
                "submitted": false,
                "method": method,
                "target": after.publicDictionary
            ]
        )
    }

    private func runSelfTest() throws -> [String: Any] {
        credentialOperationLock.lock()
        defer { credentialOperationLock.unlock() }

        guard trustedHost || brokerSelfTestBuild else {
            throw BrokerError.message(
                "The end-to-end self-test must be launched by the signed Codex or Claude host."
            )
        }

        let account = "self-test-\(UUID().uuidString)"
        let synthetic = "Synthetic-\(UUID().uuidString)"
        var syntheticData = Data(synthetic.utf8)
        let window: SelfTestWindow = DispatchQueue.main.sync {
            let window = SelfTestWindow()
            window.showAndFocus()
            return window
        }
        defer {
            syntheticData.resetBytes(in: 0..<syntheticData.count)
            KeychainStore.delete(account: account)
            DispatchQueue.main.sync { window.close() }
        }

        try KeychainStore.save(
            account: account,
            data: syntheticData,
            label: "MacBook Credential Broker Synthetic Self-Test"
        )

        let approved = requestApproval(
            message: "Run the MacBook credential broker's synthetic end-to-end test? It will create a temporary fake Keychain secret, fill it into the broker's own secure test field, compare it internally, clear the field, and delete the item. No real credential is used or revealed.",
            fieldTitle: "Approve synthetic self-test"
        )
        guard approved else {
            return toolResult(
                "The synthetic self-test ended without approval. Its temporary item was deleted.",
                structured: [
                    "approved": false,
                    "passed": false,
                    "realCredentialUsed": false,
                    "secretReturned": false
                ]
            )
        }

        DispatchQueue.main.sync { window.showAndFocus() }
        Thread.sleep(forTimeInterval: 0.2)
        let target = try TargetInspector.capture()
        guard target.pid == getpid(), target.isSecureField, !target.containsWebArea else {
            throw BrokerError.message("The broker-owned synthetic secure field could not be re-verified.")
        }

        var stored = try KeychainStore.read(account: account)
        defer { stored.resetBytes(in: 0..<stored.count) }
        let method = try CredentialInjector.fill(stored, into: target)
        Thread.sleep(forTimeInterval: 0.1)
        let passed: Bool = DispatchQueue.main.sync {
            window.field.stringValue == synthetic
        }
        guard passed else {
            throw BrokerError.message("The protected fill did not reach the synthetic secure field.")
        }

        return toolResult(
            "The synthetic end-to-end test passed. The fake Keychain item and field contents were cleared; no real credential was used or returned.",
            structured: [
                "approved": true,
                "passed": true,
                "realCredentialUsed": false,
                "secretReturned": false,
                "temporaryItemDeleted": true,
                "method": method
            ]
        )
    }

    private func handleRequest(_ message: [String: Any]) {
        guard let method = message["method"] as? String else {
            if let id = message["id"] {
                let key = idKey(id)
                pendingLock.lock()
                let waiter = pending[key]
                pendingLock.unlock()
                waiter?.fulfill(message)
            }
            return
        }

        if method.hasPrefix("notifications/") { return }
        guard let id = message["id"] else { return }

        switch method {
        case "initialize":
            let params = message["params"] as? [String: Any]
            let requestedProtocol = params?["protocolVersion"] as? String ?? "2025-06-18"
            sendResult(id: id, result: [
                "protocolVersion": requestedProtocol,
                "capabilities": ["tools": ["listChanged": false]],
                "serverInfo": [
                    "name": "macbook-credential-broker",
                    "version": brokerVersion
                ],
                "instructions": "This server never exposes credential content. Sensitive fills require one-time elicitation approval and a re-verified signed native secure-dialog target."
            ])

        case "ping":
            sendResult(id: id, result: [:])

        case "tools/list":
            sendResult(id: id, result: ["tools": Self.tools])

        case "tools/call":
            let params = message["params"] as? [String: Any] ?? [:]
            let name = params["name"] as? String ?? ""
            let arguments = params["arguments"] as? [String: Any] ?? [:]
            DispatchQueue.global(qos: .userInitiated).async { [weak self] in
                guard let self else { return }
                self.sendResult(
                    id: id,
                    result: self.handleTool(name: name, arguments: arguments)
                )
            }

        default:
            sendError(id: id, code: -32601, message: "Method not found: \(method)")
        }
    }

    func readLoop() {
        while let line = readLine(strippingNewline: true) {
            guard !line.isEmpty,
                  let data = line.data(using: .utf8),
                  let object = try? JSONSerialization.jsonObject(with: data),
                  let message = object as? [String: Any] else {
                continue
            }
            handleRequest(message)
        }
        exit(0)
    }
}

private enum ProvisioningUI {
    static func run() -> Int32 {
        NSApplication.shared.setActivationPolicy(.accessory)
        NSApp.activate(ignoringOtherApps: true)

        let password = NSSecureTextField(frame: NSRect(x: 0, y: 0, width: 420, height: 26))
        password.placeholderString = "Mac login password"
        let confirmation = NSSecureTextField(frame: NSRect(x: 0, y: 0, width: 420, height: 26))
        confirmation.placeholderString = "Confirm Mac login password"

        let explanation = NSTextField(wrappingLabelWithString: "The value goes directly from this protected field into your login Keychain. It is never printed, copied to the clipboard, sent to Codex or Claude, or placed in shell history.")
        explanation.maximumNumberOfLines = 0
        explanation.preferredMaxLayoutWidth = 420

        let stack = NSStackView(views: [explanation, password, confirmation])
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = 12
        stack.frame = NSRect(x: 0, y: 0, width: 420, height: 118)
        password.widthAnchor.constraint(equalToConstant: 420).isActive = true
        confirmation.widthAnchor.constraint(equalToConstant: 420).isActive = true

        let alert = NSAlert()
        alert.messageText = "Save Mac login password for approved fills"
        alert.informativeText = "Credential alias: \(macLoginAccount)"
        alert.alertStyle = .informational
        alert.accessoryView = stack
        alert.addButton(withTitle: "Save to Keychain")
        alert.addButton(withTitle: "Cancel")
        alert.window.initialFirstResponder = password

        defer {
            password.stringValue = ""
            confirmation.stringValue = ""
        }

        guard alert.runModal() == .alertFirstButtonReturn else {
            print("Credential provisioning cancelled. No Keychain item was changed.")
            return 1
        }
        guard !password.stringValue.isEmpty else {
            print("Credential provisioning stopped: the password was empty.")
            return 2
        }
        guard password.stringValue == confirmation.stringValue else {
            print("Credential provisioning stopped: the two protected entries did not match.")
            return 2
        }

        var data = Data(password.stringValue.utf8)
        defer { data.resetBytes(in: 0..<data.count) }
        do {
            try KeychainStore.save(
                account: macLoginAccount,
                data: data,
                label: "MacBook Credential Broker — Mac login password"
            )
            print("The macos-login credential alias is configured in Keychain. The secret was not printed.")
            return 0
        } catch {
            print("Credential provisioning failed safely: \(error)")
            return 3
        }
    }
}

@main
private struct MacBookCredentialBrokerMain {
    static func main() {
        let arguments = Array(CommandLine.arguments.dropFirst())
        switch arguments.first {
        case "mcp":
            NSApplication.shared.setActivationPolicy(.accessory)
            let server = BrokerServer()
            DispatchQueue.global(qos: .userInitiated).async {
                server.readLoop()
            }
            NSApp.run()

        case "provision":
            guard arguments.count == 2, arguments[1] == macLoginAccount else {
                fputs("Usage: macbook-credential-broker provision macos-login\n", stderr)
                exit(64)
            }
            exit(ProvisioningUI.run())

        case "--version", "version":
            print(brokerVersion)

        default:
            fputs("Usage: macbook-credential-broker <mcp|provision macos-login|--version>\n", stderr)
            exit(64)
        }
    }
}
