import type { NextConfig } from "next";

const API_URL = process.env.API_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  devIndicators: false, // the dev badge overlays the sidebar footer
  // Same-origin proxy: no CORS, and the browser never needs to know the backend host.
  // It must be a *fallback* rewrite. Next's order is: filesystem routes -> afterFiles rewrites -> dynamic routes ->
  // fallback rewrites. Auth.js lives in a dynamic catch-all (/api/auth/[...nextauth]); an afterFiles proxy would
  // swallow it and forward /api/auth/* to the backend. Fallback runs only when nothing in this app matched.
  async rewrites() {
    return { fallback: [{ source: "/api/:path*", destination: `${API_URL}/:path*` }] };
  },
};

export default nextConfig;
