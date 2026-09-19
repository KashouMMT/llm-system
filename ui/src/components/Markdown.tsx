import { isValidElement } from "react";
import ReactMarkdown from "react-markdown";
import { Link } from "react-router-dom";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";

import { fileDownloadUrl } from "../api/client";
import MermaidDiagram from "./MermaidDiagram";
import TableScroll from "./TableScroll";

const FILE_LINK = /^\/files\/([0-9a-f-]{36})$/i;

type MarkdownProps = {
	children: string;
	isStreaming?: boolean;
};

const Markdown = ({ children, isStreaming = false }: MarkdownProps) => {
	return (
		<ReactMarkdown
			remarkPlugins={[remarkGfm]}
			// detect: false — only highlight fences with an explicit
			// language (```python), rather than guessing on every plain
			// ```code``` block, which is both unreliable and wasted work
			// on every re-render while a message is still streaming.
			rehypePlugins={[[rehypeHighlight, { detect: false }]]}
			components={{
				// `rest` is deliberately not forwarded: react-markdown
				// passes the hast `node` among the props, and spreading it
				// onto a DOM element renders node="[object Object]".
				// className carries everything this element actually needs.
				code({ className, children: codeChildren }) {
					const language = /language-(\w+)/.exec(
						className ?? "",
					)?.[1];

					if (language === "mermaid") {
						return (
							<MermaidDiagram
								chart={String(codeChildren).replace(/\n$/, "")}
								isStreaming={isStreaming}
							/>
						);
					}

					return <code className={className}>{codeChildren}</code>;
				},
				pre({ children: preChildren }) {
					// Check the code element's props, not its type: at this
					// point the child is our own `code` component, not the
					// MermaidDiagram it will eventually return.
					if (
						isValidElement<{ className?: string }>(preChildren) &&
						/language-mermaid/.test(
							preChildren.props.className ?? "",
						)
					) {
						return <>{preChildren}</>;
					}

					return <pre>{preChildren}</pre>;
				},
				// A GFM table can run wider than the chat column (many
				// columns, long cell text) and taller than the viewport.
				// TableScroll gives it a horizontal scrollbar both below
				// the table and mirrored above it, so long tables don't
				// force scrolling down first to find the way to pan across.
				table({ children: tableChildren }) {
					return (
						<TableScroll>
							<table>{tableChildren}</table>
						</TableScroll>
					);
				},
				// The backend links a stored file as a relative /files/<id>
				// (e.g. catalog evidence images). Relative is right behind
				// nginx, where UI and API share an origin, but in local dev
				// the API is a different origin — so point it at the API
				// explicitly.
				//
				// Any other root-relative link is a page of this app (the
				// catalog link a recycling tool posts): followed through the
				// router, so the chat is not reloaded from scratch. Absolute
				// and protocol-relative (//host) links are left as written.
				a({ href, children: linkChildren }) {
					const fileId = href?.match(FILE_LINK)?.[1];

					if (fileId) {
						return <a href={fileDownloadUrl(fileId)}>{linkChildren}</a>;
					}

					if (href?.startsWith("/") && !href.startsWith("//")) {
						return <Link to={href}>{linkChildren}</Link>;
					}

					return <a href={href}>{linkChildren}</a>;
				},
			}}
		>
			{children}
		</ReactMarkdown>
	);
};

export default Markdown;
