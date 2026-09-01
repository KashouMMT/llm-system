import { useEffect, useId, useRef, useState } from "react";
import mermaid from "mermaid";

mermaid.initialize({
	startOnLoad: false,
	securityLevel: "strict",
	theme: "neutral",
});

type MermaidDiagramProps = {
	chart: string;
};

/**
 * Renders one mermaid code fence to SVG.
 *
 * Model output arrives token by token, so `chart` is frequently an
 * unterminated diagram mid-stream (a dangling arrow, an unclosed
 * subgraph). mermaid.render() rejects those — we keep the last
 * successful render on screen rather than clearing it on every failed
 * intermediate attempt, so the diagram doesn't flicker while it types.
 */
const MermaidDiagram = ({ chart }: MermaidDiagramProps) => {
	const id = useId().replace(/:/g, "-");
	const containerRef = useRef<HTMLDivElement>(null);
	const [pending, setPending] = useState(false);

	useEffect(() => {
		let cancelled = false;

		const render = async () => {
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
				setPending(false);
			} catch {
				if (!cancelled) {
					setPending(true);
				}
			}
		};

		void render();

		return () => {
			cancelled = true;
		};
	}, [chart, id]);

	return (
		<div className="mermaid-diagram">
			<div ref={containerRef} />
			{pending && (
				<p className="text-secondary small mb-0">Diagram pending…</p>
			)}
		</div>
	);
};

export default MermaidDiagram;
