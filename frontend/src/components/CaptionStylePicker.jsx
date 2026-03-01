const STYLE_OPTIONS = [
    { id: 'hormozi', label: 'Hormozi', preview: 'NOBODY TALKS ABOUT THIS' },
    { id: 'podcast_subtitle', label: 'Podcast', preview: 'Nobody actually talks about the real reason...' },
    { id: 'karaoke', label: 'Karaoke', preview: 'Nobody actually talks about...' },
    { id: 'reaction', label: 'Reaction', preview: 'Nobody talks about this 👀' },
    { id: 'cinematic', label: 'Cinematic', preview: 'nobody actually talks about this' },
]

export default function CaptionStylePicker({ selected, onChange }) {
    return (
        <div className="flex flex-wrap gap-2">
            {STYLE_OPTIONS.map(s => (
                <button
                    key={s.id}
                    onClick={() => onChange(s.id)}
                    className={`group px-3 py-2 rounded-lg text-xs transition-all duration-200 ${selected === s.id
                            ? 'bg-[var(--color-accent)]/20 border border-[var(--color-accent)]/40 text-[var(--color-accent-light)]'
                            : 'bg-[var(--color-bg-primary)] border border-[var(--color-border)] text-[var(--color-text-muted)] hover:border-[var(--color-border-light)] hover:text-[var(--color-text-secondary)]'
                        }`}
                >
                    <div className="font-medium">{s.label}</div>
                    <div className="mt-0.5 text-[10px] opacity-60 truncate max-w-[120px]">{s.preview}</div>
                </button>
            ))}
        </div>
    )
}
