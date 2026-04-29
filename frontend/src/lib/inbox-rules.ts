import type { Email } from "@/lib/types";

export const VIP_DOMAINS = ["cooperhealth.org", "rowan.edu", ".edu", "kennedyhealth.org"];
export const ACTION_WORDS = /\b(urgent|action required|please review|sign|approve|deadline|due|invoice|appointment|interview|offer|reminder)\b/i;
export const DEMOTED_FOLDERS = new Set([
  "Promotions",
  "Updates",
  "Forums",
  "Newsletters",
  "Junk",
  "Junk Email",
  "Junk E-mail",
  "Clutter",
]);
export const NEWSLETTER_PATTERNS = [/-?noreply@/i, /newsletter/i, /no-?reply/i, /donotreply/i];

export function scoreEmail(e: Email): number {
  let s = 0;
  // Use from_email (raw address) when available — more reliable for domain
  // extraction since `from` may be a display name like "Canvas <noreply@...>".
  const emailField = e.from_email || e.from || "";
  const domain = (emailField.match(/@([^>\s]+)/)?.[1] ?? "").toLowerCase();
  if (VIP_DOMAINS.some((d) => domain.endsWith(d.replace(/^\./, "")))) s += 50;
  const matches = (e.subject ?? "").match(new RegExp(ACTION_WORDS, "gi"))?.length ?? 0;
  s += Math.min(matches * 5, 15);
  if (e.folder && DEMOTED_FOLDERS.has(e.folder)) s -= 40;
  return s;
}

export function isNewsletter(e: Email): boolean {
  return NEWSLETTER_PATTERNS.some((p) => p.test(e.from));
}
