import { claimNotFound, fetchClaimPdf } from "@/lib/claims";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ token: string }> },
) {
  const { token } = await params;
  const pdf = await fetchClaimPdf(token);
  if (!pdf) return claimNotFound();
  return new Response(pdf, {
    headers: {
      "content-type": "application/pdf",
      "content-disposition": 'inline; filename="claim.pdf"',
      "cache-control": "no-store",
      "x-robots-tag": "noindex",
    },
  });
}
