# AI Job Navigator — Operations Manual

**Audience:** anyone accessing, testing, or supporting the AI Job Navigator web application.

**Purpose:** to document how to reach the site, how each part of the interface works, and what is and is not finished in the current deployment.

*Each screenshot's numbered legend table describes the callouts it is meant to carry. The images below do not yet have arrows or numbers drawn on them — add those to match each legend before distributing this document.*

---

## 1. Accessing the Site

The application is currently reachable at:

```
https://dev-test.career-lamp.com/
```

This is a temporary address for the current testing phase. See §13 for the planned move to the production domain.

---

## 2. Creating an Account (Sign Up)

New visitors create an account from the sign-up page. An account created this way is a **standard user** — it has no administrative privileges.

![Sign-up page](C:/Personal/Work_Folder/llm-system/images/screenshots/signup.png)

| # | Element | Description |
|---|---|---|
| 1 | Email field | The address used to sign in afterward. |
| 2 | Password field | No confirmation field — type carefully. |
| 3 | "Sign up" button | Disabled until both fields are filled. |
| 4 | "Already have an account?" link | Switches to the sign-in page. |
| 5 | Error message area | Shown if the email is already registered, or on other failures. |

After a successful sign-up, you are returned to the sign-in page — registering does not sign you in automatically; sign in with the same credentials next.

---

## 3. Signing In

![Sign-in page](C:/Personal/Work_Folder/llm-system/images/screenshots/login.png)

| # | Element | Description |
|---|---|---|
| 1 | Email field | |
| 2 | Password field | |
| 3 | "Sign in" button | Disabled until both fields are filled. |
| 4 | "Need an account?" link | Switches to the sign-up page. |
| 5 | Error message area | Shown on an incorrect email/password combination. |

Once signed in, the session stays valid for about 30 days on that browser — you will not normally need to sign in again until then, or until you sign out.

---

## 4. Elevated (Root) Access

One pre-existing account has elevated privileges, for administrative use:

```
Email:    root@localhost
Password: <redacted — replace with the current value before sharing this document>
```

At present the interface does not visibly change for this account — the Setting page (§13) is not yet built out. The elevated role exists today for administrative access at the API level, ahead of the interface that will expose it.

---

## 5. Top Navigation Bar

![Top navigation bar](C:/Personal/Work_Folder/llm-system/images/screenshots/navbar.png)

| # | Element | Description |
|---|---|---|
| 1 | Home button | Returns to the main chat view. |
| 2 | Setting button | Opens the settings page (currently empty — see §13). |
| 3 | Language switcher | Toggles interface labels between English and 日本語. Does **not** change the language the assistant replies in — see §8. |
| 4 | Theme toggle | Switches between light and dark mode. |

---

## 6. Sidebar

![Sidebar](C:/Personal/Work_Folder/llm-system/images/screenshots/sidebar.png)

| # | Element | Description |
|---|---|---|
| 1 | "+ New chat" button | Starts a new, empty conversation. |
| 2 | Conversation list | One entry per conversation, titled automatically (see §7). |
| 3 | Rename (pencil) icon | Appears when hovering a conversation; click it to edit the title in place. |
| 4 | "Blank forms" section | See §10. |
| 5 | 履歴書 (Rirekisho) download link | |
| 6 | 職務経歴書 (Shokumu Keirekisho) download link | |
| 7 | Signed-in account email | |
| 8 | "Sign out" button | See §11. |

---

## 7. Starting and Renaming Conversations

Click **+ New chat** to start a conversation. After the first exchange, the assistant generates a title for it automatically — there is no need to name it yourself.

To rename a conversation: hover over it in the sidebar, click the pencil icon that appears, edit the title, then press Enter or click elsewhere to save. An empty title is rejected.

There is currently no way to delete a conversation from the interface.

---

## 8. Chatting with the Assistant

![Chat area](C:/Personal/Work_Folder/llm-system/images/screenshots/chat-window.png)

| # | Element | Description |
|---|---|---|
| 1 | Connection status | See table below. |
| 2 | Message list | Your messages and the assistant's replies. |
| 3 | "Generating…" indicator | Shown while the assistant is composing a reply. |
| 4 | Message input field | Placeholder text reads "Type a message...". |
| 5 | Attach-file button | See §9. |
| 6 | Attached file preview | Shown once a file finishes uploading, with a remove option. |
| 7 | Send button | Disabled — see conditions below. |

**Connection status meanings** (element 1 above): this reflects the live connection between your browser and the server for streaming replies — it is not a measure of whether the assistant itself is available.

| Status shown | Meaning |
|---|---|
| No conversation | No conversation is currently open. |
| Connecting… | The browser is establishing the live connection. |
| Online | Connected; replies will stream in as they are generated. |
| Disconnected | The live connection dropped — reload the page to reconnect. |

**Send button is disabled when:**
- no conversation is open,
- the message box is empty **and** no file is attached,
- a reply is already being sent or generated, or
- a file is still uploading.

**Language note:** the assistant replies in whichever language you write to it in, regardless of the interface language switcher (§5) — the two are independent. Write in English or Japanese (or switch mid-conversation) and the assistant follows.

---

## 9. Attaching Files

Click the attach button (paperclip) to add a file to your next message.

| Limit | Value |
|---|---|
| Maximum file size | 20 MB per file |
| Maximum total per message | 100 MB combined |
| Maximum attachments per message | 10 files |
| Supported types | Images (PNG, JPEG, WebP), PDF, plain text (UTF-8 or Shift_JIS) |

A file outside these limits, or of an unsupported type, is rejected with an on-screen error before it is sent.

**What the assistant can actually use from an attachment:**
- **PDF and text files** — content can be read in full, including in later turns of the same conversation.
- **Images** — visible to the assistant only on the turn they are attached; if you refer back to an image in a later message, it is no longer visible and must be re-attached.

---

## 10. Downloading Blank Forms

The sidebar's "Blank forms" section (§6, elements 4–6) offers two blank document templates for direct download at any time, independent of any conversation:

- **履歴書 (Rirekisho)** — the standard Japanese résumé format.
- **職務経歴書 (Shokumu Keirekisho)** — the detailed work-history document.

These are empty templates, useful as a reference for the format the assistant produces when it generates a filled document during a conversation.

---

## 11. Language and Appearance

- **Language switcher** (§5, element 3) — changes interface labels (buttons, menus, messages) between English and Japanese. Saved per browser.
- **Theme toggle** (§5, element 4) — switches between light and dark mode. Saved per browser.

---

## 12. Signing Out

Click **Sign out** in the sidebar (§6, element 8) to end your session on that browser immediately. You will need to sign in again to continue.

---

## 13. Current Limitations and Roadmap

The following are known, deliberate gaps in the current deployment — not defects to report:

- **Temporary domain.** `dev-test.career-lamp.com` is a testing address. Production use will move to the apex domain, `career-lamp.com`.
- **Sign-in/sign-up page design.** The current layout is functional but a placeholder; a refined visual design is planned before public launch.
- **No rate limit on account creation.** Repeated sign-ups are not currently throttled. Please avoid creating accounts in bulk while testing — a countermeasure against abuse is planned before public launch.
- **Not publicly discoverable.** The site is not registered with Google Search Console and is not indexed by search engines.
- **Setting page is empty.** The page exists and is reachable (§5, element 2) but has no functionality yet; this will be populated in a future release.
