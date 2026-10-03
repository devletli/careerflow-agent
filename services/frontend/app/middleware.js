import { NextResponse } from "next/server";

const API_KEY = process.env.API_KEY;

export function middleware(request) {
  // Only proxy API calls and health check
  if (request.nextUrl.pathname.startsWith("/api/") || request.nextUrl.pathname === "/health-check") {
    const response = NextResponse.next();
    if (process.env.API_KEY) {
      response.headers.set("x-api-key", process.env.API_KEY);
    }
    return response;
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/api/:path*", "/health-check"],
};