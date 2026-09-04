import { useEffect, useId, useRef, useState } from "react";
import mermaid from "mermaid";

mermaid.initialize({
	startOnLoad: false,
	securityLevel: "strict",
	theme: "neutral",
});

type MermaidDiagramProps = {
	chart: string;
	/**
	 * True while the message this diagram belongs to is still streaming in.
	 * A half-typed diagram never parses, and asking mermaid to render one on
	 * every animation frame leaves orphaned error graphics in <body> that
	 * only a full page reload clears — so we don't call mermaid at all until
	 * the fence is complete.
	 */
	isStreaming?: boolean;
};

type RenderState = "waiting" | "ok" | "invalid";

const MermaidDiagram = ({ chart, isStreaming = false }: MermaidDiagramProps) => {
	const id = useId().replace(/:/g, "-");
	const containerRef = useRef<HTMLDivElement>(null);
	const [state, setState] = useState<RenderState>("waiting");

	useEffect(() => {
		if (isStreaming) {
			setState("waiting");
			return;
		}

		let cancelled = false;

		const render = async () => {
			// parse() validates without touching the DOM; it is render() on
			// invalid input that leaves error artifacts behind.
			const parsed = await mermaid
				.parse(chart, { suppressErrors: true })
				.catch(() => false);

			if (cancelled) {
				return;
			}

			if (!parsed) {
				setState("invalid");
				return;
			}

			try {
				const { svg, bindFunctions } = await mermaid.render(
					`mermaid-${id}`,
					chart,
				);

				if (cancelled || !containerRef.current) {
					return;
				}

				containerRef.current.innerHTML = svg;
				bindFunctions?.(containerRef.current);
				setState("ok");
			} catch {
				// Keep the last good SVG on screen; just flag the failure.
				if (!cancelled) {
					setState("invalid");
				}
			}
		};

		void render();

		return () => {
			cancelled = true;
		};
	}, [chart, id, isStreaming]);

	// Belt and braces: drop any measurement node mermaid may have left in
	// <body> so nothing lingers past this component.
	useEffect(() => {
		return () => {
			document.getElementById(`mermaid-${id}`)?.remove();
			document.getElementById(`dmermaid-${id}`)?.remove();
		};
	}, [id]);

	return (
		<div className="mermaid-diagram">
			<div ref={containerRef} />

			{state === "waiting" && (
				<p className="text-secondary small mb-0">
					{isStreaming
						? "Diagram will render when the response finishes…"
						: "Diagram pending…"}
				</p>
			)}

			{state === "invalid" && (
				<p className="text-secondary small mb-0">
					Diagram could not be rendered.
				</p>
			)}
		</div>
	);
};

export default MermaidDiagram;
