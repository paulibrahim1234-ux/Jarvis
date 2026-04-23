import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async rewrites() {
    const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";
    return {
      beforeFiles: [
        {
          source: "/api/apps/:path*",
          destination: `${backendUrl}/apps/:path*`,
        },
      ],
    };
  },
  /* config options here */
};

export default nextConfig;
