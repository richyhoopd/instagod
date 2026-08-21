import type { NextConfig } from "next";

const API_URL = process.env.API_URL ?? "http://127.0.0.1:8100";

const nextConfig: NextConfig = {
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
