import type { NextConfig } from "next";

const configuredDistDir = process.env.GEO_NEXT_DIST_DIR?.trim();

const nextConfig: NextConfig = {
  typedRoutes: true,
  devIndicators: false,
  // `next build` replaces the production output directory. Keep the local
  // development server in a separate directory so a verification build cannot
  // invalidate CSS and chunks that open browser sessions are still using.
  distDir: configuredDistDir || (process.env.NODE_ENV === "development" ? ".next-dev" : ".next"),
};

export default nextConfig;
