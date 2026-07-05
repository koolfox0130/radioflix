import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      {
        source: "/programs/:path*",
        destination: "http://127.0.0.1:8000/programs/:path*",
      },
      {
        source: "/api/programs/:path*",
        destination: "http://127.0.0.1:8000/api/programs/:path*",
      },
      {
        source: "/recommendations/:path*",
        destination: "http://127.0.0.1:8000/recommendations/:path*",
      },
      {
        source: "/api/recommendations/:path*",
        destination: "http://127.0.0.1:8000/api/recommendations/:path*",
      },
      {
        source: "/audio/:path*",
        destination: "http://127.0.0.1:8000/audio/:path*",
      },
      {
        source: "/api/audio/:path*",
        destination: "http://127.0.0.1:8000/api/audio/:path*",
      },
    ];
  },
};

export default nextConfig;
