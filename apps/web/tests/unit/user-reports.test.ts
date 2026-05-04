import assert from "node:assert/strict";
import test from "node:test";

const userReportsModulePath = "../../app/lib/user-reports.ts";
const { postUserReport, UserReportSubmitError } = (await import(userReportsModulePath)) as typeof import(
  "../../app/lib/user-reports"
);

test("postUserReport sends the anonymous report payload and returns pending response", async () => {
  const calls: Array<{ input: string; init?: RequestInit }> = [];
  const fetcher: typeof fetch = async (input, init) => {
    calls.push({ input: String(input), init });
    return jsonResponse({ report_id: "report-123", status: "pending" }, 202);
  };

  const response = await postUserReport(
    "https://api.example.test",
    {
      point: { lat: 25.033, lng: 121.5654 },
      summary: "Water over curb.",
    },
    fetcher,
  );

  assert.deepEqual(response, { report_id: "report-123", status: "pending" });
  assert.equal(calls[0].input, "https://api.example.test/v1/reports");
  assert.equal(calls[0].init?.method, "POST");
  assert.deepEqual(calls[0].init?.headers, { "Content-Type": "application/json" });
  assert.equal(
    calls[0].init?.body,
    JSON.stringify({
      point: { lat: 25.033, lng: 121.5654 },
      summary: "Water over curb.",
    }),
  );
});

test("postUserReport maps report gate responses to typed errors", async () => {
  await assert.rejects(
    postUserReport(
      "https://api.example.test",
      { point: { lat: 25.033, lng: 121.5654 }, summary: "Water over curb." },
      async () => jsonResponse({ error: { code: "feature_disabled" } }, 404),
    ),
    (error) => error instanceof UserReportSubmitError && error.code === "feature_disabled",
  );

  await assert.rejects(
    postUserReport(
      "https://api.example.test",
      { point: { lat: 25.033, lng: 121.5654 }, summary: "Water over curb." },
      async () => jsonResponse({ error: { code: "repository_unavailable" } }, 503),
    ),
    (error) => error instanceof UserReportSubmitError && error.code === "repository_unavailable",
  );
});

test("postUserReport maps unexpected responses to a generic submit error", async () => {
  await assert.rejects(
    postUserReport(
      "https://api.example.test",
      { point: { lat: 25.033, lng: 121.5654 }, summary: "Water over curb." },
      async () => new Response("not json", { status: 500 }),
    ),
    (error) => error instanceof UserReportSubmitError && error.code === "report_submit_failed",
  );
});

function jsonResponse(body: unknown, status: number): Response {
  return new Response(JSON.stringify(body), {
    headers: { "Content-Type": "application/json" },
    status,
  });
}
