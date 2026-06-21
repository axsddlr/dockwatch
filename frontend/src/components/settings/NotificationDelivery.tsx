function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <label className="block text-xs font-medium text-[var(--color-text-muted)]">{label}</label>
      {children}
    </div>
  )
}

export function NotificationDelivery({
  webhookUrl,
  discordWebhook,
  ntfyUrl,
  onChange,
}: {
  webhookUrl: string
  discordWebhook: string
  ntfyUrl: string
  onChange: (field: string, value: string) => void
}) {
  return (
    <section className="space-y-4">
      <h3 className="text-sm font-semibold text-[var(--color-text-primary)]">Notification Delivery</h3>
      <Field label="Webhook URL">
        <input
          type="text"
          value={webhookUrl}
          onChange={(e) => onChange('webhook_url', e.target.value)}
          placeholder="https://example.com/webhook"
          className="w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 py-2 text-sm text-[var(--color-text-primary)] placeholder-[var(--color-text-dim)] focus:border-[var(--color-primary)] focus:outline-none"
        />
      </Field>
      <Field label="Discord Webhook URL">
        <input
          type="text"
          value={discordWebhook}
          onChange={(e) => onChange('discord_webhook', e.target.value)}
          placeholder="https://discord.com/api/webhooks/..."
          className="w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 py-2 text-sm text-[var(--color-text-primary)] placeholder-[var(--color-text-dim)] focus:border-[var(--color-primary)] focus:outline-none"
        />
      </Field>
      <Field label="ntfy URL">
        <input
          type="text"
          value={ntfyUrl}
          onChange={(e) => onChange('ntfy_url', e.target.value)}
          placeholder="https://ntfy.sh/mytopic"
          className="w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 py-2 text-sm text-[var(--color-text-primary)] placeholder-[var(--color-text-dim)] focus:border-[var(--color-primary)] focus:outline-none"
        />
      </Field>
    </section>
  )
}
