import { useEffect, useRef, type ReactNode } from "react";

import "../assets/css/tableScroll.css";

type TableScrollProps = {
	children: ReactNode;
};

/**
 * Wraps a wide table in two horizontally-scrolling strips: the real one
 * below the table, and a bare mirror above it, kept in sync by scrollLeft.
 * Native scroll containers only ever put their scrollbar at the bottom, so
 * a tall table's own scrollbar is off-screen unless the reader scrolls
 * down first — the top strip is a second scrollbar with nothing to look
 * at, there purely so it's reachable from wherever the table is scrolled
 * to vertically.
 */
const TableScroll = ({ children }: TableScrollProps) => {
	const topRef = useRef<HTMLDivElement>(null);
	const topSpacerRef = useRef<HTMLDivElement>(null);
	const bottomRef = useRef<HTMLDivElement>(null);

	useEffect(() => {
		const top = topRef.current;
		const topSpacer = topSpacerRef.current;
		const bottom = bottomRef.current;

		if (!top || !topSpacer || !bottom) {
			return;
		}

		// The top strip has no content of its own — this spacer is what
		// gives it the same scroll range as the table below.
		const syncWidth = () => {
			topSpacer.style.width = `${bottom.scrollWidth}px`;
		};

		syncWidth();

		const resizeObserver = new ResizeObserver(syncWidth);
		resizeObserver.observe(bottom);

		// Reentrancy guard: without it, each side's own scroll handler
		// setting the other side's scrollLeft would fire that side's
		// handler in turn, bouncing back and forth.
		let syncing = false;

		const onTopScroll = () => {
			if (syncing) {
				return;
			}

			syncing = true;
			bottom.scrollLeft = top.scrollLeft;
			syncing = false;
		};

		const onBottomScroll = () => {
			if (syncing) {
				return;
			}

			syncing = true;
			top.scrollLeft = bottom.scrollLeft;
			syncing = false;
		};

		top.addEventListener("scroll", onTopScroll);
		bottom.addEventListener("scroll", onBottomScroll);

		return () => {
			resizeObserver.disconnect();
			top.removeEventListener("scroll", onTopScroll);
			bottom.removeEventListener("scroll", onBottomScroll);
		};
	}, []);

	return (
		<div className="table-scroll-group">
			<div className="table-scroll-top" ref={topRef}>
				<div ref={topSpacerRef} />
			</div>

			<div className="table-scroll" ref={bottomRef}>
				{children}
			</div>
		</div>
	);
};

export default TableScroll;
