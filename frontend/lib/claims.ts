const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const TOKEN = /^[\w-]{20,64}$/;

/** Server-side only: the backend stays private, this is the one thing the tunnel reaches. */
export async function fetchClaimPdf(
  token: string,
): Promise<ArrayBuffer | null> {
  if (!TOKEN.test(token)) return null;
  const response = await fetch(`${BASE}/claims/${token}.pdf`, {
    cache: "no-store",
    signal: AbortSignal.timeout(10_000),
  }).catch(() => null);
  return response?.ok ? response.arrayBuffer() : null;
}

export function claimNotFound(): Response {
  return new Response("This claim link is no longer available.", {
    status: 404,
    headers: { "content-type": "text/plain; charset=utf-8" },
  });
}
