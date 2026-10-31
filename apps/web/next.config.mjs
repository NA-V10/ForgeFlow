/** @type {import('next').NextConfig} */
const api = process.env.FORGEFLOW_API_URL || "http://localhost:8000";

const nextConfig = {
  reactStrictMode: true,
  // The browser talks to the API through this proxy, so no CORS setup is needed.
  async rewrites() {
    return [{ source: "/api/v1/:path*", destination: `${api}/api/v1/:path*` }];
  },
};

export default nextConfig;
