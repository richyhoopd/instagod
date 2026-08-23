import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

const COOKIE = "instagod_session";

const PUBLIC_PATHS = ["/login", "/auth"];

function esPublica(pathname: string): boolean {
  return PUBLIC_PATHS.some((p) => pathname === p || pathname.startsWith(`${p}/`));
}

export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;

  if (esPublica(pathname)) {
    return NextResponse.next();
  }

  if (!request.cookies.has(COOKIE)) {
    const url = new URL("/login", request.url);
    return NextResponse.redirect(url);
  }

  return NextResponse.next();
}

export const config = {
  matcher: [
    "/((?!api|_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico)$).*)",
  ],
};
