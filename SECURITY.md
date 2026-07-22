# Security Policy 安全政策

Taiwan Flood Risk Open Map is a public-interest service. Vulnerabilities can
directly affect public trust in flood-risk information, so reports are taken
seriously and handled with priority.

本專案是公益服務，安全漏洞會直接影響公眾對淹水風險資訊的信任，我們會優先處理所有通報。

## Reporting a Vulnerability 通報漏洞

**Please do NOT open a public issue for security vulnerabilities.**
請不要用公開 issue 通報安全漏洞。

Preferred channel 建議管道:

1. **GitHub Private Vulnerability Reporting**:
   [Report a vulnerability](https://github.com/pcedison/taiwan-flood-risk-open-map/security/advisories/new)
   (private to maintainers; supports coordinated disclosure)
2. **Email**: pcedison@gmail.com — subject line starting with `[SECURITY]`

Include if possible 通報內容盡量包含:

- Affected endpoint/component and file path 受影響端點/元件與檔案路徑
- Reproduction steps or proof of concept 重現步驟或 PoC
- Impact assessment 影響評估（誰會受害、多嚴重）

## Response Targets 回應目標

- Acknowledgement within **7 days** 七天內回覆確認
- Triage decision (severity + fix plan) within **14 days** 十四天內給出評級與修復計畫
- Credit given in release notes unless you prefer anonymity
  修復公告會註明貢獻者（可要求匿名）

## Scope Notes 範圍說明

- The production service (floodrisk.cc) runs on limited public-interest
  infrastructure. **Do not run DoS/load tests against production.** Use the
  local Docker Compose environment (see README Quick Start) for testing.
  正式站跑在有限的公益基礎設施上，請勿對正式站做 DoS／壓力測試；測試請用本機環境。
- Data-privacy issues (e.g., anything conflicting with
  `docs/adr/0006-privacy-preserving-query-heat.md`) are in scope and treated
  as security reports. 隱私問題視同安全通報。

## Supported Versions 支援版本

Only the latest `main` branch and the currently deployed production release
receive security fixes. 僅 `main` 與目前部署中的版本會收到安全修復。
