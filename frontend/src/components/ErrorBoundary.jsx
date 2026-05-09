import React from "react";

/*
  Catches any uncaught render error in its children and shows a useful
  message instead of the React 18 "blank screen" default in production
  builds. Forwards a copy-to-clipboard button so the user can give us
  the actual error string when reporting bugs.
  
  RESET ON NAVIGATION: pass a `resetKey` prop (e.g. location.pathname) to
  automatically clear the error state when the user navigates to another
  route — otherwise a crash on /portal/payments would persist when the user
  opens /portal/dashboard.
*/
export class ErrorBoundary extends React.Component {
  state = { error: null, info: null };

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    this.setState({ info });
    // eslint-disable-next-line no-console
    console.error("[ErrorBoundary]", this.props.name || "anonymous", error, info);
  }

  componentDidUpdate(prevProps) {
    if (this.state.error && prevProps.resetKey !== this.props.resetKey) {
      // Route changed — clear the error so the new page can render
      this.setState({ error: null, info: null });
    }
  }

  copyDetails = () => {
    const txt = `${this.state.error?.message || this.state.error}\n\n${this.state.info?.componentStack || ""}`;
    navigator.clipboard?.writeText(txt).then(() => {
      // eslint-disable-next-line no-alert
      alert("Détails de l'erreur copiés dans le presse-papiers.");
    });
  };

  render() {
    if (this.state.error) {
      return (
        <div className="m-6 rounded-2xl ring-1 ring-rose-300 bg-rose-50 p-6 text-rose-900" data-testid="error-boundary">
          <h2 className="font-display font-bold text-lg mb-2">⚠️ Une erreur est survenue dans cet écran</h2>
          <p className="text-sm mb-3">
            {this.state.error?.message || String(this.state.error)}
          </p>
          {this.state.info?.componentStack && (
            <details className="mt-2 text-[11px]">
              <summary className="cursor-pointer font-semibold">Détails techniques</summary>
              <pre className="mt-1 max-h-60 overflow-auto whitespace-pre-wrap bg-rose-100 p-2 rounded">
                {this.state.info.componentStack}
              </pre>
            </details>
          )}
          <div className="flex gap-2 mt-4">
            <button onClick={() => window.location.reload()} className="rounded-lg bg-rose-600 hover:bg-rose-700 text-white px-4 py-2 text-sm">Recharger la page</button>
            <button onClick={this.copyDetails} className="rounded-lg ring-1 ring-rose-300 bg-white hover:bg-rose-100 px-4 py-2 text-sm">Copier les détails</button>
            <button onClick={() => this.setState({ error: null, info: null })} className="rounded-lg ring-1 ring-rose-300 bg-white hover:bg-rose-100 px-4 py-2 text-sm" data-testid="error-boundary-dismiss">Réessayer</button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

