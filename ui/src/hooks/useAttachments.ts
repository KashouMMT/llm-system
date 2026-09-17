import type { TFunction } from "i18next";
import { useCallback, useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError, uploadFile } from "../api/client";
import { useAuth } from "../auth/AuthContext";

// Mirrors SendMessageRequest.attachment_ids's max_length in
// app/runtime/server.py: 10 per message, 500 for admin/root. Enforced here
// too, or a batch under the size cap but over the count would upload fine
// and only fail once Send is pressed.
export const MAX_ATTACHMENT_COUNT = 10;
export const MAX_ATTACHMENT_COUNT_ADMIN = 500;

// Mirrors UPLOAD_MAX_BYTES's default in app/config/settings.py (every
// non-video file, admin included). Checked here so an oversized file is
// refused at once instead of after uploading; the server's limit is the real
// one.
export const MAX_UPLOAD_BYTES = 20 * 1024 * 1024;

// A video has no per-file cap; its bound is the daily upload allowance
// (UPLOAD_DAILY_BYTES_PER_USER's default). A video larger than the whole
// allowance can never succeed, so it is refused before uploading. Skipped for
// admin/root, who have no allowance. The browser can't know how much of today's
// allowance is already used — the server answers that with 429.
export const MAX_VIDEO_UPLOAD_BYTES = 1024 * 1024 * 1024;

// What the file picker offers. A convenience only — the server decides
// the type from the bytes and ignores extensions entirely — so this lists
// the common extensions for each supported type, and the picker's "All
// files" option can still send anything else to be judged by the server.
export const ACCEPTED_FILE_TYPES = [
	"image/png",
	"image/jpeg",
	"image/webp",
	"application/pdf",
	".txt",
	".md",
	".csv",
	".json",
].join(",");

// The video button's picker. Separate from ACCEPTED_FILE_TYPES because a
// video is its own kind of send — see isVideoFile's use in addFiles.
export const ACCEPTED_VIDEO_TYPES = [
	"video/mp4",
	"video/quicktime",
	".mp4",
	".mov",
	".mkv",
	".webm",
].join(",");

const VIDEO_EXTENSIONS = [".mp4", ".mov", ".mkv", ".webm"];

// By claimed MIME type first, extension second: Windows reports no type at
// all for .mkv. Only a hint — the server sniffs the bytes — but the one-video
// rule below needs to know before uploading, not after.
export function isVideoFile(file: File): boolean {
	if (file.type.startsWith("video/")) {
		return true;
	}

	const name = file.name.toLowerCase();

	return VIDEO_EXTENSIONS.some((extension) => name.endsWith(extension));
}

export type AttachmentSlot = {
	// Client-local, so a slot can be identified and removed before the
	// server has assigned it a real id (or if it never does, on error).
	localId: string;
	file: File;
	status: "uploading" | "done" | "error";
	// Set once the upload resolves. What actually gets sent as
	// attachment_ids.
	id: string | null;
	errorMessage: string | null;
};

function newLocalId(): string {
	return typeof crypto.randomUUID === "function"
		? crypto.randomUUID()
		: `${Date.now()}-${Math.random()}`;
}

/**
 * Maps a failed upload to interface text by status rather than showing
 * the server's `detail`, which is English — the two statuses a user can
 * cause and fix themselves get their own message; everything else is the
 * generic one.
 */
function describeUploadError(caught: unknown, t: TFunction): string {
	if (caught instanceof ApiError) {
		if (caught.status === 413) {
			return t("chat.attachmentFileTooLarge");
		}

		if (caught.status === 415) {
			return t("chat.attachmentUnsupported");
		}

		if (caught.status === 429) {
			return t("chat.attachmentQuotaExceeded");
		}
	}

	return t("chat.attachmentError");
}

/**
 * Manages the composer's pending attachments: upload starts the moment a
 * file is picked, independent of whether the user has typed anything or
 * is ready to send yet.
 *
 * Keyed by conversationId at the call site (ChatPage), the same way
 * useChat and useConversationStream are — not inside Chat — so that
 * invariant (everything here describes the one selected conversation)
 * stays visible in one place rather than re-derived per hook.
 */
export const useAttachments = (conversationId: string | undefined) => {
	const { t } = useTranslation();
	const auth = useAuth();
	const [slots, setSlots] = useState<AttachmentSlot[]>([]);

	// Mirrors is_admin(user) in app/authentication/authorization.py — admin
	// and root get the relaxed count limit and no daily upload allowance.
	const isAdmin =
		auth.status === "authenticated" &&
		(auth.user.role === "admin" || auth.user.role === "root");
	const maxAttachmentCount = isAdmin
		? MAX_ATTACHMENT_COUNT_ADMIN
		: MAX_ATTACHMENT_COUNT;
	const maxVideoUploadBytes = isAdmin ? Infinity : MAX_VIDEO_UPLOAD_BYTES;

	const updateSlot = useCallback(
		(localId: string, patch: Partial<AttachmentSlot>) => {
			setSlots((previous) =>
				previous.map((slot) =>
					slot.localId === localId ? { ...slot, ...patch } : slot,
				),
			);
		},
		[],
	);

	const addFiles = useCallback(
		(files: FileList | File[]) => {
			if (!conversationId) {
				return;
			}

			// A rejected slot doesn't count — it was never uploaded.
			let count = slots.filter((slot) => slot.status !== "error").length;

			// A video is sent alone: one video, nothing else with it. Mirrors
			// the check in MessageRepository.create_turn, which is the real
			// enforcement — this only saves uploading something that send
			// would refuse.
			const videoQueued = slots.some(
				(slot) => slot.status !== "error" && isVideoFile(slot.file),
			);
			const incoming = Array.from(files);

			const added: AttachmentSlot[] = [];
			const toUpload: Array<{ localId: string; file: File }> = [];

			for (const file of incoming) {
				const localId = newLocalId();
				const isVideo = isVideoFile(file);

				if (videoQueued || (isVideo && (count > 0 || incoming.length > 1))) {
					added.push({
						localId,
						file,
						status: "error",
						id: null,
						errorMessage: t("chat.attachmentVideoAlone"),
					});
					continue;
				}

				if (count >= maxAttachmentCount) {
					added.push({
						localId,
						file,
						status: "error",
						id: null,
						errorMessage: t("chat.attachmentTooMany", {
							limit: maxAttachmentCount,
						}),
					});
					continue;
				}

				if (file.size > (isVideo ? maxVideoUploadBytes : MAX_UPLOAD_BYTES)) {
					added.push({
						localId,
						file,
						status: "error",
						id: null,
						errorMessage: t(
							isVideo
								? "chat.attachmentVideoTooLarge"
								: "chat.attachmentFileTooLarge",
						),
					});
					continue;
				}

				count += 1;

				added.push({
					localId,
					file,
					status: "uploading",
					id: null,
					errorMessage: null,
				});
				toUpload.push({ localId, file });
			}

			setSlots((previous) => [...previous, ...added]);

			for (const { localId, file } of toUpload) {
				uploadFile(conversationId, file)
					.then((uploaded) => {
						updateSlot(localId, { status: "done", id: uploaded.id });
					})
					.catch((caught) => {
						updateSlot(localId, {
							status: "error",
							errorMessage: describeUploadError(caught, t),
						});
					});
			}
		},
		[
			conversationId,
			slots,
			t,
			updateSlot,
			maxAttachmentCount,
			maxVideoUploadBytes,
		],
	);

	const removeSlot = useCallback((localId: string) => {
		setSlots((previous) => previous.filter((slot) => slot.localId !== localId));
	}, []);

	const clear = useCallback(() => setSlots([]), []);

	return {
		slots,
		addFiles,
		removeSlot,
		clear,
		// Gates the composer's admin-only folder-upload control.
		isAdmin,
		// What sendMessage actually needs — only fully uploaded slots.
		attachedIds: slots
			.filter((slot) => slot.status === "done" && slot.id !== null)
			.map((slot) => slot.id as string),
		isUploading: slots.some((slot) => slot.status === "uploading"),
	};
};

export type Attachments = ReturnType<typeof useAttachments>;
