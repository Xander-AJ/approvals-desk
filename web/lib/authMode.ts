/**
 * "oidc" (default): sign in with GitHub via Auth.js; the server mints API tokens for allowlisted users only.
 * "dev": anyone can pick any role from a dropdown. Local demos and Playwright only: set explicitly.
 * Secure by default: an unset variable means real sign-in. (NEXT_PUBLIC_* is inlined at build time.)
 */
export const AUTH_MODE: "dev" | "oidc" = process.env.NEXT_PUBLIC_AUTH_MODE === "dev" ? "dev" : "oidc";
