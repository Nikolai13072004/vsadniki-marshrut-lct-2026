import { NextRequest, NextResponse } from "next/server";

// This edition is local-only. Reject foreign Host headers before API proxying.
export function proxy(request: NextRequest) {
  if (
    !/^(localhost|127\.0\.0\.1|\[::1\])(?::\d+)?$/i.test(
      request.headers.get("host") || "",
    )
  ) {
    return new NextResponse(
      "Локальная версия доступна только через localhost.",
      { status: 400 },
    );
  }
  return NextResponse.next();
}
