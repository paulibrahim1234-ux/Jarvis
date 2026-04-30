import type { Email } from "@/lib/types";

// Dropped bare ".edu" — too broad (every university address gets +50 for free).
export const VIP_DOMAINS = ["cooperhealth.org", "rowan.edu", "kennedyhealth.org"];
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
// Folders whose emails get a +20 signal boost (user confirmed these carry important mail).
export const IMPORTANT_FOLDERS = new Set(["Inbox", "Rowan class of 2027"]);

// Added \bannouncer\b and \bdigest\b to catch Rowan Announcer / digest mailers.
// Added marketing@ and info@ as newsletter-sender patterns.
export const NEWSLETTER_PATTERNS = [
  /-?noreply@/i,
  /newsletter/i,
  /no-?reply/i,
  /donotreply/i,
  /\bannouncer\b/i,
  /\bdigest\b/i,
  /\bmarketing@/i,
  /\binfo@/i,
];

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
  // Boost emails arriving in folders the user identified as important.
  if (e.folder && IMPORTANT_FOLDERS.has(e.folder)) s += 20;
  // Newsletter penalty: VIP domain alone shouldn't make a Rowan Announcer email
  // "Important". Subtract 35 so newsletter emails from rowan.edu land at ~15
  // instead of ~50, well below the 40 threshold.
  if (isNewsletter(e)) s -= 35;
  return s;
}

export function isNewsletter(e: Email): boolean {
  // Test the raw email address, not the display name. "Canvas Notifications
  // <noreply@canvas.rowan.edu>" has the noreply marker only in from_email.
  const addr = e.from_email || e.from || "";
  return NEWSLETTER_PATTERNS.some((p) => p.test(addr));
}
