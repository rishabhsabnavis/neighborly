import { claimNotFound, fetchClaimPdf } from "@/lib/claims";

// A plain route, not a page: the root layout would wrap this in the agent console.
export async function GET(
  _request: Request,
  { params }: { params: Promise<{ token: string }> },
) {
  const { token } = await params;
  if (!(await fetchClaimPdf(token))) return claimNotFound();
  const pdf = `/claims/${token}/pdf`;
  const html = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>Claim summary</title>
<style>
  html, body { height: 100%; margin: 0; background: #f2f4f7; font-family: -apple-system, system-ui, sans-serif; }
  body { display: flex; flex-direction: column; }
  header { display: flex; justify-content: space-between; align-items: center; padding: 12px 16px; background: #fff; border-bottom: 1px solid #e4e7ec; color: #1d2939; font-size: 16px; font-weight: 600; }
  a { color: #175cd3; font-size: 15px; font-weight: 500; }
  iframe { flex: 1; width: 100%; border: 0; }
</style>
</head>
<body>
<header><span>Claim summary</span><a href="${pdf}">Open PDF</a></header>
<iframe src="${pdf}" title="Claim summary PDF"></iframe>
</body>
</html>`;
  return new Response(html, {
    headers: {
      "content-type": "text/html; charset=utf-8",
      "cache-control": "no-store",
      "x-robots-tag": "noindex",
    },
  });
}
