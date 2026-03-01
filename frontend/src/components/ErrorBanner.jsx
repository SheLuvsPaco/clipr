export default function ErrorBanner({ error, onRetry, onStartOver }) {
    if (!error) return null

    return (
        <div className="p-4 rounded-xl border border-[var(--color-danger)]/30 bg-[var(--color-danger)]/5 animate-in fade-in">
            <div className="flex items-start gap-3">
                <span className="text-xl mt-0.5">⚠</span>
                <div className="flex-1">
                    <p className="font-medium text-[var(--color-danger)]">
                        {error.type || 'Something went wrong'}
                    </p>
                    <p className="mt-1 text-sm text-[var(--color-text-secondary)]">
                        {error.message || String(error)}
                    </p>
                </div>
                <div className="flex gap-2 shrink-0">
                    {onRetry && (
                        <button onClick={onRetry} className="px-3 py-1.5 text-xs font-medium rounded-lg bg-[var(--color-bg-card)] hover:bg-[var(--color-bg-hover)] border border-[var(--color-border)] transition-colors">
                            Retry
                        </button>
                    )}
                    {onStartOver && (
                        <button onClick={onStartOver} className="px-3 py-1.5 text-xs font-medium rounded-lg text-[var(--color-danger)] hover:bg-[var(--color-danger)]/10 transition-colors">
                            Start over
                        </button>
                    )}
                </div>
            </div>
        </div>
    )
}
