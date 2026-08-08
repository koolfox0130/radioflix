import type { NextConfig } from "next";

const apiBaseUrl =
  process.env.RADIOFLIX_API_URL ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  allowedDevOrigins: ["radioflix.kool-fox.com"],
  async rewrites() {
    return [
      {
        source: "/programs/:path*",
        destination: `${apiBaseUrl}/programs/:path*`,
      },
      {
        source: "/api/programs/:path*",
        destination: `${apiBaseUrl}/api/programs/:path*`,
      },
      {
        source: "/recommendations/:path*",
        destination: `${apiBaseUrl}/recommendations/:path*`,
      },
      {
        source: "/api/recommendations/:path*",
        destination: `${apiBaseUrl}/api/recommendations/:path*`,
      },
      {
        source: "/audio/:path*",
        destination: `${apiBaseUrl}/audio/:path*`,
      },
      {
        source: "/api/audio/:path*",
        destination: `${apiBaseUrl}/api/audio/:path*`,
      },
    ];
  },
};

export default nextConfig;
