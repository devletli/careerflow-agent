import { NextResponse } from "next/server";

// Attaches the shared API key to proxied backend requests server-side,
// so the key never reaches the browser (no NEXT_PUBLIC_ variable is used).
// The next.config.js rewrites then forward these requests to the API.
export function middleware(request) {
  const apiKey = process.env.API_KEY;
  if (!apiKey) {
    return NextResponse.next();
  }
  const headers = new Headers(request.headers);
  headers.set("x-api-key", apiKey);
  return NextResponse.next({ request: { headers } });
}

export const config = {
  matcher: ["/api/:path*", "/health-check"],
};
