/** @type {import('next').NextConfig} */
const API_ORIGIN = process.env.API_INTERNAL_URL || "http://api:8000";

const nextConfig = {
  // The browser only ever talks to this Next.js server on the same origin.
  // Requests to /api/* and /health are proxied server-side to the API
  // service so the dashboard works regardless of the host the browser
  // uses to reach the frontend container (localhost, docker network, etc).
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${API_ORIGIN}/api/:path*` },
      { source: "/health-check", destination: `${API_ORIGIN}/health` },
    ];
  },
};

module.exports = nextConfig;
