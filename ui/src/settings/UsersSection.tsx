import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "../api/client";
import type {
	AssignableRole,
	ManagedUser,
	UpdateUserRequest,
} from "../api/types";
import { useAuth } from "../auth/AuthContext";
import TableScroll from "../components/TableScroll";
import {
	useCreateUser,
	useDeleteUser,
	useUpdateUser,
	useUsers,
} from "../hooks/useUsers";

const ROLES: readonly AssignableRole[] = ["user", "admin"];

type Draft = { email: string; password: string; role: AssignableRole };

const EMPTY_DRAFT: Draft = { email: "", password: "", role: "user" };

const errorMessage = (error: unknown, fallback: string): string =>
	// 404 / 409 / 422 carry the server's reason as a string: the rules
	// (root is not editable, email taken) are enforced there.
	error instanceof ApiError && typeof error.detail === "string"
		? error.detail
		: fallback;

type RowProps = {
	user: ManagedUser;
	isSelf: boolean;
	onError: (message: string | null) => void;
};

/** One account: read-only, or its inline edit form. */
const UserRow = ({ user, isSelf, onError }: RowProps) => {
	const { t } = useTranslation();
	const update = useUpdateUser();
	const remove = useDeleteUser();

	const [editing, setEditing] = useState(false);
	const [draft, setDraft] = useState<Draft>(EMPTY_DRAFT);

	const busy = update.isPending || remove.isPending;
	const created = new Date(user.created_at).toLocaleDateString();

	const startEditing = () => {
		// The root row never reaches here; the cast is only for the type.
		setDraft({ email: user.email, password: "", role: user.role as AssignableRole });
		setEditing(true);
		onError(null);
	};

	const save = () => {
		// Only what changed, and a password only when one was typed — blank
		// means "keep the current one", not "set an empty password".
		const body: UpdateUserRequest = {};

		if (draft.email.trim() !== user.email) {
			body.email = draft.email.trim();
		}

		if (draft.role !== user.role) {
			body.role = draft.role;
		}

		if (draft.password) {
			body.password = draft.password;
		}

		if (Object.keys(body).length === 0) {
			setEditing(false);
			return;
		}

		update.mutate(
			{ id: user.id, body },
			{
				onSuccess: () => {
					setEditing(false);
					onError(null);
				},
				onError: (error) => onError(errorMessage(error, t("settings.users.errGeneric"))),
			},
		);
	};

	const confirmDelete = () => {
		if (!window.confirm(t("settings.users.confirmDelete", { email: user.email }))) {
			return;
		}

		remove.mutate(user.id, {
			onSuccess: () => onError(null),
			onError: (error) => onError(errorMessage(error, t("settings.users.errGeneric"))),
		});
	};

	if (user.role === "root") {
		return (
			<tr>
				<td>
					{user.email}
					{isSelf && <span className="settings-badge ms-2">{t("settings.users.you")}</span>}
				</td>
				<td>root</td>
				<td>{created}</td>
				<td className="users-note">{t("settings.users.rootManaged")}</td>
			</tr>
		);
	}

	if (editing) {
		return (
			<tr>
				<td>
					<input
						type="email"
						className="form-control form-control-sm"
						value={draft.email}
						onChange={(event) => setDraft({ ...draft, email: event.target.value })}
					/>
					<input
						type="password"
						className="form-control form-control-sm mt-1"
						placeholder={t("settings.users.newPassword")}
						autoComplete="new-password"
						value={draft.password}
						onChange={(event) => setDraft({ ...draft, password: event.target.value })}
					/>
				</td>
				<td>
					<select
						className="form-select form-select-sm"
						value={draft.role}
						onChange={(event) =>
							setDraft({ ...draft, role: event.target.value as AssignableRole })
						}
					>
						{ROLES.map((role) => (
							<option key={role} value={role}>
								{role}
							</option>
						))}
					</select>
				</td>
				<td>{created}</td>
				<td className="users-actions">
					<button type="button" className="btn btn-primary btn-sm" disabled={busy} onClick={save}>
						{t("settings.save")}
					</button>
					<button
						type="button"
						className="btn btn-outline-secondary btn-sm"
						disabled={busy}
						onClick={() => setEditing(false)}
					>
						{t("settings.users.cancel")}
					</button>
				</td>
			</tr>
		);
	}

	return (
		<tr>
			<td>{user.email}</td>
			<td>{user.role}</td>
			<td>{created}</td>
			<td className="users-actions">
				<button
					type="button"
					className="btn btn-outline-secondary btn-sm"
					disabled={busy}
					onClick={startEditing}
				>
					{t("settings.users.edit")}
				</button>
				<button
					type="button"
					className="btn btn-outline-danger btn-sm"
					disabled={busy}
					onClick={confirmDelete}
				>
					{t("settings.users.delete")}
				</button>
			</td>
		</tr>
	);
};

/**
 * ROOT → Users: every account, with create, edit (email, role, password)
 * and delete. The root account itself is listed but not editable — it is
 * managed from the server environment.
 */
const UsersSection = () => {
	const { t } = useTranslation();
	const auth = useAuth();
	const users = useUsers();
	const create = useCreateUser();

	const [draft, setDraft] = useState<Draft>(EMPTY_DRAFT);
	const [error, setError] = useState<string | null>(null);

	const selfId = auth.status === "authenticated" ? auth.user.id : null;

	const handleCreate = (event: FormEvent<HTMLFormElement>) => {
		event.preventDefault();
		setError(null);

		create.mutate(
			{ email: draft.email.trim(), password: draft.password, role: draft.role },
			{
				onSuccess: () => setDraft(EMPTY_DRAFT),
				onError: (failure) => setError(errorMessage(failure, t("settings.users.errGeneric"))),
			},
		);
	};

	return (
		<>
			<form className="users-create" onSubmit={handleCreate}>
				<input
					type="email"
					className="form-control"
					placeholder={t("settings.users.email")}
					autoComplete="off"
					required
					value={draft.email}
					onChange={(event) => setDraft({ ...draft, email: event.target.value })}
				/>
				<input
					type="password"
					className="form-control"
					placeholder={t("settings.users.password")}
					autoComplete="new-password"
					required
					value={draft.password}
					onChange={(event) => setDraft({ ...draft, password: event.target.value })}
				/>
				<select
					className="form-select"
					value={draft.role}
					onChange={(event) =>
						setDraft({ ...draft, role: event.target.value as AssignableRole })
					}
				>
					{ROLES.map((role) => (
						<option key={role} value={role}>
							{role}
						</option>
					))}
				</select>
				<button type="submit" className="btn btn-primary" disabled={create.isPending}>
					{create.isPending ? t("settings.users.creating") : t("settings.users.create")}
				</button>
			</form>

			{error && (
				<p className="settings-error" role="alert">
					{error}
				</p>
			)}

			{users.isPending && <p className="settings-status">{t("settings.loading")}</p>}

			{users.isError && <p className="settings-error">{t("settings.users.loadError")}</p>}

			{users.data && (
				<TableScroll>
					<table className="users-table">
						<thead>
							<tr>
								<th>{t("settings.users.email")}</th>
								<th>{t("settings.users.role")}</th>
								<th>{t("settings.users.created")}</th>
								<th />
							</tr>
						</thead>
						<tbody>
							{users.data.map((user) => (
								<UserRow
									key={user.id}
									user={user}
									isSelf={user.id === selfId}
									onError={setError}
								/>
							))}
						</tbody>
					</table>
				</TableScroll>
			)}
		</>
	);
};

export default UsersSection;
