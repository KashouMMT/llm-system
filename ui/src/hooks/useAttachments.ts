import type { TFunction } from "i18next";
import { useCallback, useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError, uploadFile } from "../api/client";

// A batch cap, enforced here so a pick of many files fails before any
// upload starts rather than after wasting bandwidth on some of them.
export const MAX_ATTACHMENT_TOTAL_BYTES = 100 * 1024 * 1024;

// Mirrors SendMessageRequest.attachment_ids's max_length in
// app/runtime/server.py. Enforced here too, or a batch under the size cap
// but over 10 files would upload fine and only fail once Send is pressed.
export const MAX_ATTACHMENT_COUNT = 10;

// Mirrors UPLOAD_MAX_BYTES's default in app/config/settings.py. Checked
// here so an oversized file is refused at once instead of after uploading
// 20 MB only to be told 413; the server's limit is still the real one.
export const MAX_UPLOAD_BYTES = 20 * 1024 * 1024;

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
	const [slots, setSlots] = useState<AttachmentSlot[]>([]);

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

			// A rejected slot (over count or over the size budget) doesn't
			// count against either running total — it was never uploaded, so
			// it costs the batch nothing.
			let totalBytes = slots
				.filter((slot) => slot.status !== "error")
				.reduce((sum, slot) => sum + slot.file.size, 0);
			let count = slots.filter((slot) => slot.status !== "error").length;

			const added: AttachmentSlot[] = [];
			const toUpload: Array<{ localId: string; file: File }> = [];

			for (const file of Array.from(files)) {
				const localId = newLocalId();

				if (count >= MAX_ATTACHMENT_COUNT) {
					added.push({
						localId,
						file,
						status: "error",
						id: null,
						errorMessage: t("chat.attachmentTooMany"),
					});
					continue;
				}

				if (file.size > MAX_UPLOAD_BYTES) {
					added.push({
						localId,
						file,
						status: "error",
						id: null,
						errorMessage: t("chat.attachmentFileTooLarge"),
					});
					continue;
				}

				if (totalBytes + file.size > MAX_ATTACHMENT_TOTAL_BYTES) {
					added.push({
						localId,
						file,
						status: "error",
						id: null,
						errorMessage: t("chat.attachmentTooLarge"),
					});
					continue;
				}

				totalBytes += file.size;
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
		[conversationId, slots, t, updateSlot],
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
		// What sendMessage actually needs — only fully uploaded slots.
		attachedIds: slots
			.filter((slot) => slot.status === "done" && slot.id !== null)
			.map((slot) => slot.id as string),
		isUploading: slots.some((slot) => slot.status === "uploading"),
	};
};

export type Attachments = ReturnType<typeof useAttachments>;
