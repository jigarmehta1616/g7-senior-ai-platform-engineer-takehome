import { Component, type ErrorInfo } from "react";

import type { ErrorBoundaryProps, ErrorBoundaryState } from "../types/ui";
import { Button } from "./Button";

/** Catches render errors in a subtree so one broken screen doesn't blank the whole console. */
export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  override state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: unknown): ErrorBoundaryState {
    return { error: error instanceof Error ? error.message : String(error) };
  }

  override componentDidCatch(error: unknown, info: ErrorInfo): void {
    console.error("Console screen crashed", error, info.componentStack);
  }

  private readonly reset = () => {
    this.setState({ error: null });
  };

  override render() {
    if (this.state.error === null) return this.props.children;
    return (
      <div role="alert" className="space-y-2 rounded-xl border border-l-4 border-line border-l-bad bg-surface p-4">
        <p className="font-semibold">Something went wrong on this screen.</p>
        <p className="text-sm break-words text-muted">{this.state.error}</p>
        <Button variant="ghost" onClick={this.reset}>Try again</Button>
      </div>
    );
  }
}
