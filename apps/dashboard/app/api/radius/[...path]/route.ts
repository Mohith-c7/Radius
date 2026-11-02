import { NextRequest, NextResponse } from "next/server";

import {
  MAX_BODY_BYTES,
  buildUpstreamHeaders,
  IF_MATCH_PATTERN,
  buildUpstreamUrl,
  checkRoute,
  loadProxyConfig,
} from "../../../../lib/proxy";

export const dynamic = "force-dynamic";

function error(status: number, code: string, message: string) {
  return NextResponse.json(
    { success: false, data: null, error: { code, message } },
    { status, headers: { "Cache-Control": "no-store" } },
  );
}

async function handle(request: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params;
  const verdict = checkRoute(path, request.method);
  if (verdict === "not_found") return error(404, "NOT_FOUND", "Unknown API route.");
  if (verdict === "method") return error(405, "METHOD_NOT_ALLOWED", "Method not allowed.");

  const declared = Number(request.headers.get("content-length") ?? "0");
  if (declared > MAX_BODY_BYTES) return error(413, "PAYLOAD_TOO_LARGE", "Request body too large.");

  let body: ArrayBuffer | undefined;
  if (request.method !== "GET" && request.method !== "DELETE") {
    body = await request.arrayBuffer();
    if (body.byteLength > MAX_BODY_BYTES) {
      return error(413, "PAYLOAD_TOO_LARGE", "Request body too large.");
    }
  }

  const config = loadProxyConfig();
  let upstream: Response;
  try {
    upstream = await fetch(buildUpstreamUrl(config, path, request.nextUrl.search), {
      method: request.method,
      headers: buildUpstreamHeaders(config, request.headers, {
        segments: path,
        method: request.method,
      }),
      body: body && body.byteLength > 0 ? body : undefined,
      cache: "no-store",
      redirect: "error",
      signal: AbortSignal.timeout(30_000),
    });
  } catch {
    return error(502, "UPSTREAM_UNAVAILABLE", "Radius API is unreachable.");
  }

  const text = await upstream.text();
  const responseHeaders: Record<string, string> = {
    "Content-Type": upstream.headers.get("content-type") ?? "application/json",
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
  };
  // Intent reads/writes return a strong ETag the client sends back as If-Match.
  const etag = upstream.headers.get("etag");
  if (etag && IF_MATCH_PATTERN.test(etag)) responseHeaders.ETag = etag;
  return new NextResponse(text, { status: upstream.status, headers: responseHeaders });
}

export { handle as GET, handle as POST, handle as PATCH, handle as DELETE };
