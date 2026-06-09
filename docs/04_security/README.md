# Security

Use this section for threat models, disclosure policy details, security architecture notes, and hardening guidance.

## Contents

| Doc | Topic |
|---|---|
| [llm-data-flow.md](llm-data-flow.md) | What data leaves the cluster → OpenAI on each judgment generation (feat_llm_judgments) |
| [github-token-handling.md](github-token-handling.md) | Per-repo PAT storage / rotation / scopes / leak-prevention (feat_github_pr_worker) |
| [cluster-url-ssrf.md](cluster-url-ssrf.md) | SSRF guard on cluster `base_url` — flag gate, blocked ranges, metadata denylist, DNS-rebinding residual (bug_cluster_url_ssrf_hostname_bypass) |
