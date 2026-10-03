import { NextResponse } from "next/server";

export function middleware(request) {
  // Only proxy API calls and health check. The shared API key is attached
  // to the UPSTREAM request headers server-side, so it never reaches the
  // browser (setting it on the response would leak it to the client).
  if (request.nextUrl.pathname.startsWith("/api/") || request.nextUrl.pathname === "/health-check") {
    const requestHeaders = new Headers(request.headers);
    if (process.env.API_KEY) {
      requestHeaders.set("x-api-key", process.env.API_KEY);
    }
    return NextResponse.next({ request: { headers: requestHeaders } });
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/api/:path*", "/health-check"],
};