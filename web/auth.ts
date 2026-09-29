import NextAuth from "next-auth";
import GitHub from "next-auth/providers/github";
import { allowlistFromEnv, isAllowed } from "@/lib/authz";

/** Shape we add to the Auth.js session: the IdP's immutable user id (never the mutable login name). */
export type AppSession = { ghId?: string; user?: { name?: string | null } };

export const { handlers, auth, signIn, signOut } = NextAuth({
  providers: [GitHub],
  session: { strategy: "jwt", maxAge: 8 * 60 * 60 },
  trustHost: true,
  pages: { error: "/login" }, // AccessDenied (not on the allowlist) lands on /login with a clear message
  callbacks: {
    // Deny by default: authenticating with GitHub is not enough, the account must be on the allowlist.
    signIn({ profile }) {
      return isAllowed(allowlistFromEnv(), profile?.id === undefined ? undefined : String(profile.id));
    },
    jwt({ token, profile }) {
      if (profile?.id !== undefined) token.ghId = String(profile.id);
      return token;
    },
    session({ session, token }) {
      return { ...session, ghId: typeof token.ghId === "string" ? token.ghId : undefined };
    },
  },
});
