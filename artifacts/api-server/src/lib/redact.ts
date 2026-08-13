/**
 * Redact secrets from text before it is logged or returned to a client.
 * Covers live environment values (the strongest signal) plus token-like
 * strings, so raw Python stderr can never leak a credential.
 */
const TOKEN_RE = /[A-Za-z0-9_-]{32,}/g;

export function redactSecrets(text: string): string {
  let out = text;
  for (const [key, value] of Object.entries(process.env)) {
    if (!value || value.length < 8 || value === "[REDACTED]") continue;
    const sensitive = /(secret|token|password|credential|api[_-]?key|private)/i.test(key);
    if (!sensitive && value.length < 24) continue;
    // split/join = single-pass global replacement, no regex escaping issues
    // and no infinite-loop risk.
    out = out.split(value).join("[REDACTED]");
  }
  return out.replace(TOKEN_RE, "[REDACTED]");
}
