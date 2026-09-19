import { API_BASE_URL } from "../../api/client";

// The empty forms a user can take without talking to the assistant first,
// shown in the chat sidebar and on the plugin's settings page. Kept here
// rather than fetched: the two document types are fixed, and a request
// just to learn their names would delay the sidebar for nothing.
export const BLANK_FORMS = [
	{ docType: "rirekisho", label: "履歴書", hint: "Rirekisho" },
	{
		docType: "shokumu_keirekisho",
		label: "職務経歴書",
		hint: "Shokumu Keirekisho",
	},
];

/**
 * For plain anchors, like the message attachments in Chat: the response
 * carries Content-Disposition: attachment, so the browser downloads
 * without navigating away and the SameSite=Lax session cookie rides along
 * on the GET.
 */
export const blankDocumentUrl = (docType: string): string =>
	`${API_BASE_URL}/plugins/recruitment/blank/${docType}`;
