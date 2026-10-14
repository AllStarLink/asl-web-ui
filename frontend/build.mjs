// Bundle the frontend into dist/ with esbuild.
//   node build.mjs            production build
//   node build.mjs --watch    rebuild on change (development)

import * as esbuild from "esbuild";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";

const watch = process.argv.includes("--watch");
const version = process.env.RELVER || "devel";

await rm("dist", { recursive: true, force: true });
await mkdir("dist", { recursive: true });

const html = await readFile("public/index.html", "utf8");
await writeFile("dist/index.html", html.replaceAll("@@HEAD-DEVELOP@@", version));

const options = {
  entryPoints: { app: "src/main.tsx" },
  bundle: true,
  outdir: "dist",
  minify: !watch,
  sourcemap: watch ? "inline" : false,
  target: ["es2022"],
  legalComments: "linked",
  define: { __ASL_WEB_UI_VERSION__: JSON.stringify(version) },
  loader: {
    ".woff": "file",
    ".woff2": "file",
    ".svg": "file",
    ".png": "file",
    ".jpg": "file",
  },
  assetNames: "assets/[name]-[hash]",
  logLevel: "info",
};

if (watch) {
  const ctx = await esbuild.context(options);
  await ctx.watch();
} else {
  await esbuild.build(options);
}
