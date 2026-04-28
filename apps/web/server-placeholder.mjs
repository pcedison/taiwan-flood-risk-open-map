import { createServer } from "node:http";

const port = Number(process.env.WEB_PORT ?? 3000);
const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

const html = `<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Flood Risk</title>
    <style>
      body { margin: 0; font-family: system-ui, sans-serif; background: #0f172a; color: #f8fafc; }
      main { min-height: 100vh; display: grid; place-items: center; padding: 24px; }
      section { width: min(960px, 100%); display: grid; gap: 16px; }
      .map { min-height: 420px; border: 1px solid #334155; background: #1e293b; display: grid; place-items: center; }
      .panel { display: flex; justify-content: space-between; gap: 16px; flex-wrap: wrap; color: #cbd5e1; }
    </style>
  </head>
  <body>
    <main>
      <section>
        <div class="map">Taiwan</div>
        <div class="panel"><span>API: ${apiBaseUrl}</span><span>Risk: unknown</span></div>
      </section>
    </main>
  </body>
</html>`;

const server = createServer((request, response) => {
  if (request.url === "/health") {
    response.writeHead(200, { "content-type": "application/json" });
    response.end(JSON.stringify({ status: "ok", service: "web", runtime: "placeholder" }));
    return;
  }

  response.writeHead(200, { "content-type": "text/html; charset=utf-8" });
  response.end(html);
});

server.listen(port, "0.0.0.0", () => {
  console.log(JSON.stringify({ event: "web.placeholder_started", port }));
});
