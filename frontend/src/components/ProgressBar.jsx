export default function ProgressBar({ percent = 0, className = '' }) {
    return (
        <div className={`w-full h-2 bg-[var(--color-bg-primary)] rounded-full overflow-hidden ${className}`}>
            <div
                className="h-full rounded-full bg-gradient-to-r from-[var(--color-accent)] to-[var(--color-accent-light)] transition-all duration-500 ease-out"
                style={{ width: `${Math.min(100, Math.max(0, percent))}%` }}
            />
        </div>
    )
}
