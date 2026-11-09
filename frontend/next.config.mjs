/** @type {import('next').NextConfig} */
const api = process.env.ATLAS_API_URL || "http://localhost:8000";
const nextConfig = {
  output: "standalone",
  reactStrictMode: true,
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${api}/api/:path*` }];
  },
};
export default nextConfig;
