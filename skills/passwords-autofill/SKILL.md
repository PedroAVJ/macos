---
name: passwords-autofill
description: Use Apple's iCloud Passwords extension to autofill an existing login in Chrome when the user asks for Apple Passwords or its native prompt is active. Ordinary Chrome password-manager sign-ins and website verification codes are outside this skill.
---

# Autofill with Apple Passwords

Use the connected Chrome profile and the existing login tab. Trigger Apple's autofill without reading, copying, or typing saved passwords or passkey responses. If the native Passwords app needs unlocking, use this plugin's `credential-authorization` broker only after verifying its `passwords-unlock` target and obtaining the user's approval; its `macos-login` credential must never go into a webpage. For local iCloud Passwords extension pairing, verify the official extension before using Apple's pairing prompt. Submit the website login only when the user authorized it, and preserve an unfinished challenge tab across turns. Handle website verification through the normal authorized login workflow; this skill imposes no additional restriction on it.
