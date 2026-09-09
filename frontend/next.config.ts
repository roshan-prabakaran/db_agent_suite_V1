import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  allowedDevOrigins: ['100.114.251.120'],

  // Increase proxy timeout to 5 minutes for long-running LLM/agent requests
  experimental: {
    proxyTimeout: 300_000,   // 5 minutes in ms
  },

  // Keep HTTP connections alive to avoid premature disconnects
  httpAgentOptions: {
    keepAlive: true,
  },

  rewrites: async () => {
    // For Docker networking, use the API container hostname, fallback to localhost for dev
    const apiUrl = process.env.API_URL || "http://127.0.0.1:8000";
    return [
      {
        source: "/api/:path*",
        destination: `${apiUrl}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
