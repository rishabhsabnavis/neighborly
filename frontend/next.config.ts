import type { NextConfig } from "next";

// Venue networks can block the backend's hostname, so production browsers call
// the API through this site's own domain.
const useApiProxy = process.env.NEXT_PUBLIC_USE_API_PROXY === "1";

const nextConfig: NextConfig = {
  rewrites() {
    if (!useApiProxy) return Promise.resolve([]);
    return Promise.resolve([
      {
        source: "/backend/:path*",
        destination: `${process.env.NEXT_PUBLIC_API_URL}/:path*`,
      },
    ]);
  },
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
