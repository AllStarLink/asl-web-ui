// Injected by esbuild (build.mjs).
declare const __ASL_WEB_UI_VERSION__: string;

// Stylesheets are bundled by esbuild.
declare module "*.css";

// Images are copied to dist/assets/ by esbuild; the import is their URL.
declare module "*.png" {
  const url: string;
  export default url;
}
