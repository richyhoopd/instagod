import type { NextConfig } from "next";

const API_URL = process.env.API_URL ?? "http://127.0.0.1:8100";

const nextConfig: NextConfig = {
  // La e2e usa su propio distDir para convivir con un `next dev` ya vivo (lock en .next/dev).
  distDir: process.env.NEXT_DIST_DIR ?? ".next",
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${API_URL}/:path*`,
      },
    ];
  },
};

export default nextConfig;
