// Bundle the frontend into dist/ with esbuild.
//   node build.mjs            production build
//   node build.mjs --watch    rebuild on change (development)

import * as esbuild from "esbuild";
import { cp, mkdir, readFile, rm, writeFile } from "node:fs/promises";

const watch = process.argv.includes("--watch");
const version = process.env.RELVER || "devel";

await rm("dist", { recursive: true, force: true });
await mkdir("dist", { recursive: true });

const html = await readFile("public/index.html", "utf8");
await writeFile("dist/index.html", html.replaceAll("@@HEAD-DEVELOP@@", version));
// Linked from index.html by name, so copied as they are (no hash).
await cp("public/favicons", "dist/favicons", { recursive: true });

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
    ".webp": "file",
  },
  assetNames: "assets/[name]-[hash]",
  logLevel: "info",
};

// Every npm package that ends up in dist/ must have a stanza in
// debian/copyright (Files: frontend/node_modules/<package>/...).
async function checkCopyright(metafile) {
  const patterns = [];
  const text = await readFile("../debian/copyright", "utf8");
  for (const para of text.split(/\n\s*\n/)) {
    const m = para.match(/^Files:((?:.*)(?:\n .*)*)/m);
    if (!m) continue;
    for (const glob of m[1].trim().split(/\s+/)) {
      const re = glob.replace(/[.+?^${}()|[\]\\]/g, "\\$&").replaceAll("*", ".*");
      if (glob !== "*") patterns.push(new RegExp(`^${re}$`));
    }
  }
  const packages = new Set();
  for (const output of Object.values(metafile.outputs)) {
    for (const [path, input] of Object.entries(output.inputs)) {
      const m = path.match(/^node_modules\/((?:@[^/]+\/)?[^/]+)\//);
      if (m && input.bytesInOutput !== 0) packages.add(m[1]);
    }
  }
  const missing = [...packages].filter(
    (pkg) => !patterns.some((re) => re.test(`frontend/node_modules/${pkg}/package.json`)),
  );
  if (missing.length) {
    console.error(`debian/copyright has no stanza for: ${missing.sort().join(", ")}`);
    process.exit(1);
  }
}

if (watch) {
  const ctx = await esbuild.context(options);
  await ctx.watch();
} else {
  const result = await esbuild.build({ ...options, metafile: true });
  await checkCopyright(result.metafile);
}
