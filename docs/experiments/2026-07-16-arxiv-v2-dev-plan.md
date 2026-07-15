# Track B development plan — extended unified-DRA version (arXiv v2 / journal)

Status: PLAN (2026-07-16). Base = `arxiv/v1-accepted` (accepted manuscript + IEEE
notice). Material = `feature/unified-dra-fallback` (2275301). This plan is grounded
in a July-2026 web survey (5 parallel research agents; findings below). It does NOT
touch the frozen conference record (already in Xplore pipeline); it produces an
EXTENDED version for arXiv v2 and (recommended) MDPI Future Internet.

## 0. Research-grounded facts (July 2026) that shape the writing

Each fact is load-bearing and MUST be re-verified from the cited primary source
before it goes in the paper (see the adversarial-review gate).

- **Kueue v0.18.3** (2026-07-10). `KueueDRAIntegration` = Beta, default-on since v0.18.
  Official docs: `FirstAvailable` device selection and the `All` allocation mode are
  **not supported**; Kueue **rejects** such workloads (gate
  `KueueDRARejectWorkloadsWhenDRADisabled`, Beta/on). DeviceClass->quota still via
  `resources.deviceClassMappings` (config `config.kueue.x-k8s.io/v1beta2`).
  Source: https://kueue.sigs.k8s.io/docs/concepts/dynamic_resource_allocation/
- **K8s 1.36 "Haru"** (2026-04-22) is current; 1.37 GA scheduled 2026-08-26.
  DRA core GA since 1.34 (`resource.k8s.io/v1`). **`firstAvailable`/`DRAPrioritizedList`
  (KEP-4816) is GA/Stable as of 1.36** (beta in 1.34). Source: KEP-4816 impl history;
  https://kubernetes.io/blog/2026/05/07/kubernetes-v1-36-dra-136-updates/
  Caveat: no upstream KEP example shows CROSS-DRIVER GPU->CPU firstAvailable (all
  examples alternate GPU tiers within one driver). Spec permits it; upstream does not
  demonstrate it -> our cross-driver GPU+CPU claim is a novel application, state honestly.
- **dra-driver-cpu v0.2.0** (2026-06-22), pre-beta (v0.3.0 = first beta, issue #142).
  **#231** (kubelet-root-dir hardcode) still OPEN, fix deferred behind PR #213; no
  override flag shipped. Reporter = thc1006. We also merged #215.
- **NVIDIA GPU DRA driver**: repo moved to `kubernetes-sigs/dra-driver-nvidia-gpu`
  (CNCF donation ~2026-03), SemVer since v0.4.0; GPU allocation GA (v25.12.0); latest
  v0.4.1 (2026-06-30).
- **ORCHIDE**: project CLOSED (ended 2026-05-31, MS05 demo review 2026-04-23). No
  open-source ground-side tooling released; open-source release still "forthcoming"
  (project news 2026-05-21). Novelty claim HOLDS; update date to July 2026 + note
  "now formally closed, open-source forthcoming".
- **Venue recommendation**: MDPI Future Internet (topical fit — ORCHIDE's own June-2026
  paper is there, fi18060299; ~15-day first decision; APC CHF 1800; new-content bar =
  "expand to article length + cite the conference paper", no fixed %). Alternatives:
  IEEE Access ($2160, ~30d, ~30-40% informal), IEEE TCC (35%, strict, slow).
- **Candidate new citations (UNVERIFIED — must check each arXiv ID individually before
  use, per the no-AI-citation rule)**: Edge-Cloud Space Continuum (2605.04316),
  YUHENG-OS (2603.27946), K8s+Argo+Kueue hybrid quantum-classical (2603.24206),
  ClusterLess (2605.04310), Policy-as-Code adoption (2601.05555), + Equinox
  (2604.19958), EO scheduling (2604.05937), BIDENT (2606.05271).

## 1. The three sections to write (into `paper/main.tex`)

### S1 — Upgrade the fallback story (revise existing Section V-D)
Reframe the single runtime env-var fallback into TWO mechanisms:
- (a) runtime env-var `ORBITAL_FALLBACK_RESOURCE_CLASS` (existing; portable default;
  invisible to scheduler/Kueue).
- (b) NEW opt-in DRA `firstAvailable` ResourceClaim = scheduler-level "prefer GPU, else
  CPU", GA in K8s 1.36. Compiler emits it when `--dra-fallback` is set AND both the
  primary and fallback classes are DRA-backed (`DRA_DEVICE_CLASS` = {GPU: gpu.nvidia.com,
  CPU: dra.cpu}; FPGA deliberately absent — no DRA driver).
- Empirical anchor: two identical Pods with one `firstAvailable[gpu.nvidia.com, dra.cpu]`
  claim -> first gets the K2200 GPU, second auto-falls-back to a `dra.cpu` device. Same
  spec, scheduler chose.
- Honesty: cross-driver GPU+CPU firstAvailable is spec-permitted but upstream-undemonstrated
  (our application). FPGA excluded (no driver).

### S2 — NEW subsection: Unified GPU+CPU DRA quota under Kueue, and its boundary
- Mechanism: Kueue counts only `exactly` device requests. Map BOTH `gpu.nvidia.com`
  and `dra.cpu` DeviceClasses to logical quotas via `deviceClassMappings`; ClusterQueue
  covers both logical names + cpu/memory. Each accelerator class gets its own quota =
  a genuine unification (it just cannot live inside one firstAvailable claim today).
- Empirical anchor A: an `exactly` dra.cpu Job under the unified queue -> admitted and
  counted against the new `dra.cpu` quota (show flavorsUsage before/after).
- Empirical anchor B (the boundary proof): HYPOTHESIS per Kueue v0.18.3 docs = a
  `firstAvailable` claim submitted UNDER a Kueue queue is REJECTED. This is a
  DOC-DERIVED EXPECTATION, NOT yet observed on our cluster. It MUST be run and the
  ACTUAL behavior captured (reject vs ignore vs admit-and-miscount) before any sentence
  asserts it. If confirmed, it proves S1 (scheduler fallback) and S2 (Kueue quota) are
  DISJOINT capabilities as of v0.18.3 — a reproducible limitation. Do NOT write the
  outcome from the doc; write it from the run.

### S3 — Upgrade Limitations (Section VII) + a short provenance/contribution note
- firstAvailable is not Kueue-countable (upstream ENFORCES rejection); the two
  mechanisms cannot be combined in one claim today; future work pending Kueue support
  (no open KEP found proposing it).
- dra-driver-cpu is pre-beta (v0.2.0); the kubelet-root-dir override is unmerged
  (#231, deferred behind #213) -> the path-fix is a documented LOCAL workaround, not a
  shipped feature. We contributed #215 (merged) and filed #231.
- Cross-driver firstAvailable is spec-permitted but upstream-undemonstrated.
- Update all DRA maturity statements to July-2026 facts (DRA GA 1.34; firstAvailable GA
  1.36; Kueue v0.18.3). "Generalization beyond ORCHIDE" paragraph unchanged.

No schema/policy change (Rule 4 already guarantees every accelerator step has a fallback).
Render-layer + tests + manifests + prose only.

## 2. Live re-verification protocol (from `manifests/k8s/kueue/dra-unified/`)

Run on the host kubeadm cluster (thc1006-d630mt, K2200). CAPTURE every version first:
`kubectl version`, Kueue version, dra-driver-cpu version, NVIDIA driver version, node/GPU.

DECISION: upgrade Kueue v0.17.3 -> **v0.18.3** for currency (KueueDRAIntegration beta/on;
the "rejects firstAvailable" behavior is documented there). Re-run §V-E cascade too so the
paper's Kueue numbers are on one current version. (If upgrade is too disruptive, keep
0.17.3 and note it; but 0.18.3 is the stronger, current story.)

Three checks (each -> a captured artifact committed under a results/ dir, NOT scratchpad):
1. `exactly` dra.cpu Job under `dra-unified` queue -> admitted, counted against `dra.cpu`
   quota. Capture ClusterQueue flavorsUsage + workload admission resourceUsage.
2. `firstAvailable` RCT + 2 plain Pods (NO Kueue) -> GPU chosen, then CPU fallback.
   Capture which device each pod bound (ResourceClaim status allocation).
3. `firstAvailable` claim UNDER a Kueue queue -> Kueue REJECTS. Capture the exact event/
   error string (the boundary proof).
Honest race caveat for check 2/3: document any nondeterminism; do not overstate.
Cleanup: delete demo pods; keep dra-driver-cpu (patched) installed; capture teardown.

## 3. Compile + three-lens adversarial review (before any upload/submission)

- Compile the extended `main.tex` (expect page growth; arXiv has no limit; for Future
  Internet, reformat to their class later). Zero overfull; check underfull.
- Lens 1 (code-break / reproducibility): every empirical sentence maps to a committed
  manifest + captured output; all versions pinned; the race caveats are stated.
- Lens 2 (whole-paper consistency): numbers, cross-refs, citation numbering; no
  contradiction with the frozen conference claims; §V-D/§V-E internal consistency.
- Lens 3 (methodology / overclaim): cross-driver firstAvailable honesty; dra-driver-cpu
  maturity honesty; "unified quota" not overclaimed; ORCHIDE novelty date-scoped; the
  Kueue-rejection boundary stated as capability-disjoint, not as a Kueue bug.
- GATE (adversarial review 2026-07-16 output — clear ALL before writing an empirical sentence):
  1. Re-read the committed `manifests/k8s/kueue/dra-unified/` set + `install-dra-driver-cpu.sh`;
     confirm they implement S1/S2 AND that the path-fix is ENCODED (reproducible), not an
     ephemeral kubectl patch. [UNVERIFIED this session.]
  2. RUN all three live checks; capture REAL outputs. Anchor B (Kueue rejecting firstAvailable)
     is a doc-derived hypothesis until observed — observe it.
  3. Independently confirm EVERY new citation's arXiv ID (arxiv.org/abs/<id>). Spot-check
     2026-07-16: 4/8 verified real (2605.04316, 2603.27946, 2603.24206, 2601.05555 — titles/
     authors match). REMAINING UNVERIFIED: 2604.19958, 2604.05937, 2606.05271, 2606.15076,
     2606.31950, 2607.09151, Nature s41598-026-41483-6. Verify before .bib.
  4. Re-fetch MDPI Future Internet author policy + APC + timeline from mdpi.com directly
     (the survey got these from search snippets; the primary page 403'd automated fetch).
  5. Re-verify firstAvailable-GA (KEP-4816 README) and Kueue-rejection (Kueue docs) from
     primary source directly before the paper asserts either.
  6. Decide Kueue version: re-run §V-E on v0.18.3 for one-version consistency, OR explicitly
     scope "extended validation on v0.18.3" so the paper never mixes v0.17.3 and v0.18.3 numbers.
  7. Soften novelty: "we did not find an upstream example demonstrating cross-driver GPU->CPU
     firstAvailable", NOT "first". State the single-GPU precondition for the fallback demo.

## 4. Sequencing + venue

1. Decide venue: arXiv-only extended v2 (fast) vs MDPI Future Internet (recommended;
   needs "article-length" expansion). Writing S1-S3 serves both; journal adds formatting
   + more relidated-work depth.
2. Branch off `arxiv/v1-accepted` -> `paper/extended-dra` (or v0.4.3 line).
3. Live re-verification (Section 2) -> capture numbers.
4. Write S1-S3 with captured numbers + verified citations.
5. Compile + three-lens adversarial review + gate.
6. Post arXiv v2 (replace v1) and/or submit to Future Internet.

## 5. GATE PROGRESS (2026-07-16, live)

- [x] **Item 1 (manifests reproducibility) — PASS.** `install-dra-driver-cpu.sh` ENCODES
  the path-fix (auto-detects kubelet root-dir, helm install, kubectl-patch the
  plugin-registry hostPath, wait for ResourceSlice) = reproducible local workaround,
  honestly documented (chart has no override, per #231). `00` deviceClassMappings map
  BOTH gpu.nvidia.com + dra.cpu (config v1beta2). `02` has firstAvailable + exactly.
  `04` two-Pod fallback (captured 2026-07-09: demo-1->gpu-0, demo-2->cpudevnuma000).
  `05` boundary Job + comment "Record the observed behavior... rather than trusting this
  comment." compiler.py: DRA_DEVICE_CLASS (l.23), _dra_fallback_step (l.307), firstAvailable
  render (l.367), threaded through render_kueue_job. Code+manifests self-consistent.
  CAVEAT: all comments encode the v0.17.3-era EXPECTATION ("Kueue admits, ignores the
  accelerator"), which must be re-observed on the target version (see item 2/6).
- [x] **Item 3 (citations) — 7/8 must-cites VERIFIED real** (independent arxiv.org fetch,
  titles+authors match): 2605.04316, 2603.27946, 2603.24206, 2601.05555, 2604.19958,
  2604.05937, 2606.05271. STILL UNVERIFIED (optional, no-author in survey): 2606.15076,
  2606.31950, 2607.09151, Nature s41598-026-41483-6 — verify only if cited.
- [x] **Item 5 (primary re-verify) — DONE.** KEP-4816 (primary): firstAvailable Alpha1.33/
  Beta1.34/**Stable1.36**; ALL examples are within-driver GPU tiers, NO cross-driver
  example -> our cross-driver framing is correct + primary-backed. Kueue docs (primary):
  "Only `exactly` supported; FirstAvailable and All not supported" (v0.18+). CRITICAL: the
  docs DO NOT say whether firstAvailable-under-Kueue is rejected / ignored / miscounted ->
  the exact behavior is UNKNOWN from any doc and MUST be observed on-cluster (item 2).
- [x] **Item 7 — resolved.** Novelty softened to "did not find an upstream example"; single-
  GPU precondition for the fallback demo noted.
- [x] **Item 4 (MDPI policy) — DONE** (WebSearch of the primary Instructions-for-Authors page).
  Future Internet accepts an extended conference paper if: (1) expanded to research-article
  length; (2) the conference paper is cited + noted on page 1; (3) permission from the copyright
  holder if not held (IEEE holds the SMC-IT/SCC copyright -> confirm IEEE reuse allowance before
  submitting); (4) a cover letter disclosing it is an extended conference paper + a statement of
  what changed. NO fixed new-content percentage (unlike IEEE TCC 35% / JSS 30%). APC ~CHF 1800.

## VENUE DECISION (2026-07-16)

Method: venue is the LAST decision, not the first. arXiv-only and journal share the same
S1-S3 core; the journal only needs article-length expansion on top. So write the common core
first, then choose based on actual extension size.
- **Primary target = MDPI Future Internet** (journal). Rationale: ORCHIDE's own paper
  (fi18060299) is in Future Internet, so the ground-side complement sits in the same venue as
  what it complements (strongest positioning); lowest-friction journal bar ("article length" +
  cite + cover letter, no fixed %); fast (~15-day first decision), open-access, peer-reviewed.
- **arXiv v2 in parallel** (IEEE + MDPI both permit an arXiv preprint of the extended version).
- **Track A (arXiv v1, accepted version)** is already built (`arxiv/v1-accepted`, arxiv-v1/) and
  can be posted NOW for pre/post-conference visibility, independent of the extended version.
- Pre-journal-submission: confirm IEEE reuse permission for the extended version; write cover
  letter listing changes (unified DRA firstAvailable + Kueue quota + v0.18.3 re-verification).
- [x] **Item 6 (Kueue version) — DONE.** Upgraded cluster Kueue v0.17.3 -> **v0.18.3**
  (server-side apply of release manifest; re-injected deviceClassMappings into the v0.18.3
  default config; no DRA feature-gate flags needed since KueueDRAIntegration is default-on;
  controller healthy, zero config errors). Pre-upgrade backup at scratchpad/live-2026-07-16/backup/.
- [x] **Item 2 (three live checks + §V-E) — DONE on v0.18.3.** Captures in
  `manifests/k8s/kueue/dra-unified/results-v0.18.3-20260716/`. §V-E GPU cascade: dra.gpu=1,
  job-2 quota-gated. Check1 dra.cpu cascade: dra.cpu=1, job-2 quota-gated. Check2 firstAvailable
  2 Pods: gpu-0 then cpudevnuma000 (cross-driver scheduler fallback). Check3 firstAvailable
  under Kueue: **REJECTED Inadmissible** "FirstAvailable device selection is not supported".
  KEY: v0.18.3 REJECTS (not the v0.17.3-era silent-ignore) -> boundary is hard-enforced;
  manifest/compiler comments now stale; compiler render_kueue_job+firstAvailable warrants a
  guard decision. See results README.

Out of scope (honest): no FPGA DRA (no driver); no forcing all CPU steps through DRA;
no flight-ready claims; no change to the frozen conference citation.
