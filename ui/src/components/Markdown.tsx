import { isValidElement } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";

import MermaidDiagram from "./MermaidDiagram";

type MarkdownProps = {
	children: string;
};

const Markdown = ({ children }: MarkdownProps) => {
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
			}}
		>
			{children}
		</ReactMarkdown>
	);
};

export default Markdown;
