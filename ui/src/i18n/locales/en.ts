// English messages. This object's shape is the contract every other
// locale is type-checked against — see ja.ts, typed as `Messages`.
export const en = {
	nav: {
		home: "Home",
		settings: "Settings",
		themeToDark: "Switch to dark mode",
		themeToLight: "Switch to light mode",
	},
	lang: {
		label: "Language",
		english: "English",
		japanese: "日本語",
	},
	auth: {
		signUpTitle: "Create an account",
		email: "Email",
		password: "Password",
		signIn: "Sign in",
		signingIn: "Signing in…",
		signUp: "Sign up",
		creatingAccount: "Creating account…",
		needAccount: "Need an account?",
		haveAccount: "Already have an account?",
		accountCreated: "Account created — please sign in.",
		errWrongCredentials: "Incorrect email or password.",
		errSignInGeneric: "Could not sign in. Is the API running?",
		errEmailTaken: "That email is already registered.",
		errSignUpGeneric: "Could not sign up. Is the API running?",
	},
	sidebar: {
		newChat: "+ New chat",
		creating: "Creating…",
		loading: "Loading…",
		loadError: "Could not load conversations.",
		empty: "No conversations yet.",
		rename: "Rename",
		renameAria: "Rename conversation",
		signOut: "Sign out",
	},
	chat: {
		assistant: "AI Assistant",
		generating: "Generating…",
		statusIdle: "No conversation",
		statusConnecting: "Connecting…",
		statusOpen: "Online",
		statusClosed: "Disconnected",
		pickConversation: "Pick a conversation, or start a new one.",
		loadingMessages: "Loading messages…",
		loadError: "Could not load this conversation.",
		noMessages: "No messages yet — say something.",
		joinedLate:
			"Joined while an answer was already in progress — showing it from here.",
		noteInterrupted: "The server stopped before this answer finished.",
		noteCancelled: "This answer was cancelled.",
		noteFailed: "This answer failed to generate.",
		errBusy: "This conversation is already generating an answer.",
		errMissing: "This conversation no longer exists.",
		errNetwork: "Could not reach the server.",
		retry: "Retry",
		dismiss: "Dismiss",
		inputPlaceholder: "Type a message...",
		inputPlaceholderNoConv: "Select a conversation first",
		send: "Send",
		sending: "Sending…",
		attach: "Attach a file",
		attachFolder: "Attach a folder",
		attachVideo: "Attach a video",
		attachmentVideoAlone:
			"A video must be sent on its own — one video, with no other attachments.",
		attachmentVideoTooLarge: "This video is larger than the 1 GB daily upload limit.",
		attachmentUploading: "Uploading…",
		attachmentError: "Upload failed.",
		attachmentRemove: "Remove attachment",
		attachmentTooMany: "Up to {{limit}} attachments per message.",
		attachmentFileTooLarge: "This file is over the 20 MB limit.",
		attachmentUnsupported:
			"Unsupported file. Send an image (PNG, JPEG, WebP), a PDF, or a text file (UTF-8 or Shift_JIS).",
		attachmentQuotaExceeded:
			"You've reached today's upload limit. Try again tomorrow.",
	},
	settings: {
		navLabel: "Settings sections",
		categories: {
			core: "Core",
			root: "Root",
			plugin: "Plugins",
		},
		sections: {
			general: "General",
			llm: "LLM configuration",
			memory: "Memory & summarization",
			streaming: "Streaming",
			users: "Users",
		},
		users: {
			email: "Email",
			password: "Password",
			newPassword: "New password (blank keeps the current one)",
			role: "Role",
			created: "Created",
			create: "Add user",
			creating: "Adding…",
			edit: "Edit",
			cancel: "Cancel",
			delete: "Delete",
			you: "you",
			rootManaged: "Managed from the server environment",
			confirmDelete:
				"Delete {{email}}? Their conversations, messages and files are deleted too. This cannot be undone.",
			loadError: "Could not load users.",
			errGeneric: "Could not save. Is the API running?",
		},
		loading: "Loading settings…",
		loadError: "Could not load settings.",
		save: "Save",
		saving: "Saving…",
		discard: "Discard changes",
		saved: "Saved. Applies from the next turn.",
		reset: "Reset to default",
		defaultValue: "Default: {{value}}",
		sessionOnly: "Resets on restart",
		incompleteSet: "{{name}} (incomplete: runs as default)",
		errGeneric: "Could not save. Is the API running?",
		// Keys match the backend's setting names in
		// app/config/runtime_settings.py; the form looks them up by name.
		fields: {
			system_prompt_name: {
				label: "Persona",
				help: "Prompt set under app/prompts/. Also changes the greeting of new conversations.",
			},
			log_level: {
				label: "Log level",
				help: "Server log verbosity.",
			},
			temperature: {
				label: "Temperature",
				help: "Randomness of replies, 0–2. Lower sticks closer to the facts it was given.",
			},
			top_p: {
				label: "Top P",
				help: "Sample only from the most likely tokens covering this share of probability, 0–1.",
			},
			top_k: {
				label: "Top K",
				help: "Sample only from the K most likely tokens. Sent to Ollama only.",
			},
			max_tokens: {
				label: "Max reply tokens",
				help: "The longest reply the model may write. Must be less than the context window.",
			},
			context_window: {
				label: "Context window",
				help: "Token budget for prompt plus reply. Sent to Ollama only.",
			},
			summary_token_threshold: {
				label: "Summarize after (tokens)",
				help: "History size, in tokens, that triggers a summary.",
			},
			max_summary_chars: {
				label: "Summary length limit",
				help: "Maximum characters kept in the running summary.",
			},
			max_context_history_messages: {
				label: "History window",
				help: "Most recent messages sent to the model each turn.",
			},
			max_unsummarized_messages: {
				label: "Summarize after (messages)",
				help: "Backup trigger by message count. Must not exceed the history window.",
			},
			min_retained_raw_messages: {
				label: "Messages kept word for word",
				help: "Newest messages never folded into the summary. Must be less than “Summarize after (messages)”.",
			},
			max_checkpoint_messages: {
				label: "Checkpoint message cap",
				help: "Bounds stored agent state only; does not change what the model sees.",
			},
			sse_heartbeat_seconds: {
				label: "Heartbeat interval (seconds)",
				help: "How often an idle event stream sends a keep-alive.",
			},
			sse_queue_maxsize: {
				label: "Event queue size",
				help: "Events buffered per open tab before a slow tab is dropped and reconnects.",
			},
		},
	},
	error: {
		notFoundTitle: "Page not found",
		notFoundBody: "That page doesn't exist or has moved.",
		forbiddenTitle: "Request blocked",
		forbiddenBody:
			"A security check failed. Reloading the page usually fixes it.",
		serverErrorTitle: "Something went wrong",
		serverErrorBody: "An unexpected error occurred. Try reloading the page.",
		reload: "Reload",
		backHome: "Back to home",
		dismiss: "Dismiss",
	},
};

export type Messages = typeof en;
