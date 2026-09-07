/** @type {import('next').NextConfig} */
const nextConfig = {
  async redirects() {
    return [
      {
        // Root lands on the Lumina home/workspace instead of the legacy black/white UI.
        source: '/',
        destination: '/pancake',
        // temporary (307) so we can roll back easily; switch to true once stable.
        permanent: false,
      },
    ];
  },
};

export default nextConfig;
