import { Component, type ErrorInfo, type ReactNode } from "react";

import ServerErrorPage from "../layout/ServerErrorPage";

type ErrorBoundaryProps = { children: ReactNode };
type ErrorBoundaryState = { hasError: boolean };

/**
 * Catches render/lifecycle errors anywhere in the app tree and shows the
 * 500 page instead of a blank screen. Recovery is a full reload (the
 * button on ServerErrorPage) — deliberately not per-route reset, to keep
 * this simple.
 */
export class ErrorBoundary extends Component<
	ErrorBoundaryProps,
	ErrorBoundaryState
> {
	state: ErrorBoundaryState = { hasError: false };

	static getDerivedStateFromError(): ErrorBoundaryState {
		return { hasError: true };
	}

	componentDidCatch(error: Error, info: ErrorInfo): void {
		console.error("Unhandled render error:", error, info.componentStack);
	}

	render(): ReactNode {
		if (this.state.hasError) {
			return <ServerErrorPage />;
		}

		return this.props.children;
	}
}
