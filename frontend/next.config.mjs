/** @type {import('next').NextConfig} */
const nextConfig = {
  // Standalone output keeps the Docker image small.
  output: "standalone",
  // ESLint isn't scaffolded here; TypeScript type-checking still runs on build.
  eslint: { ignoreDuringBuilds: true },
};

export default nextConfig;
