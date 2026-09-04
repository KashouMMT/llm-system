# AI Job Navigator — Requirements Specification: Technical Review & Open Questions

**Subject document:** AI_Job_Navigator_Client_Requirements_Engineering_Specification_EN_Updated.docx
**Date: 29 August 2026**
**Version: v1.0**

---

## 0. Purpose of This Document

We have reviewed the requirements specification from an implementation perspective. This document sets out the items we would like confirmed or decided **before the specification is finalized and the development schedule is produced.**

The intent of this document is as follows:

- It is not a criticism of the specification. It identifies the points where a decision is required in order to implement.
- Decisions received will be reflected in the final specification, and the schedule will be produced from that.
- Some items overlap with the validation items already listed in Section 14 of the specification, "Items to Validate First."

---

## 1. Items Requiring Confirmation Before the Specification Is Finalized (Summary)

The following directly affect development scope and schedule. We would be grateful for confirmation on these as a priority.

| # | Item | Section |
|---|---|---|
| 1 | Development method (agile / waterfall) and demonstration frequency | §13 |
| 2 | MVP delivery order | §13 |
| 3 | Scope of OCR support | §5, §10 |
| 4 | Initial scope of social media integration | §3 |
| 5 | Initial scope of human support channels | §6 |
| 6 | Payment provider selection | §7 |
| 7 | Base template for 履歴書 / 職務経歴書 | §5 |
| 8 | Expected concurrent users at launch | Not stated |
| 9 | Provision of staging environment and domain | Not stated |
| 10 | Ownership of Terms of Service and Privacy Policy | Related to §12 |

---

## 2. [A] Decisions Required

Items that are undecided in the specification, or not covered by it. The schedule cannot be finalized without these.

### A-1. Development Method and Demonstration Frequency (§13)

Section 13 defines MVP 1–4 and Expansion, but does not define how the work will be conducted.

- Please advise your preferred frequency for demonstrations of working software (at the end of each phase / every two weeks / other).
- Please decide whether the project proceeds as two-week sprints (agile) or as waterfall.

The implementation content is unchanged either way; what differs is reporting frequency and how specification changes are handled.

### A-2. MVP Delivery Order (§13)

The current order is MVP 1 (job search) → MVP 2 (saved conditions and new-job notification) → MVP 3 (document creation). We would like to discuss changing this order, for two reasons:

- **Document creation (MVP 3) has no dependency on the job data acquisition pipeline.** Job data acquisition is the least certain part of this project, and confirming source specifications and completing technical validation may take time. If MVP 1 is delayed, MVP 3 can proceed in parallel, so working software can continue to be demonstrated.
- **MVP 2 and MVP 3 both require the same email-sending infrastructure.** It is more efficient either to build that infrastructure ahead of both, or to reorder the phases.

As to the current state of implementation: a prototype exists for the AI interview and for generating the document content as text. However, **file output (PDF / Word), document upload, extraction of information from uploaded documents, the user confirmation screen, and email delivery are all unimplemented.** The majority of Section 5 as a whole remains new development.

Either order is technically feasible; we would simply like to understand your preference.

### A-3. Payment Provider (§7)

Section 7 states that "Pricing plans, free-tier scope, payment provider, and cancellation rules will be finalized separately."

- Do you have a preferred payment provider? If not, we assume Stripe.
- If pricing plans, free-tier scope, and cancellation rules remain undecided, we propose placing the billing feature in a later MVP.

### A-4. Base Template for 履歴書 / 職務経歴書 (§5)

Please specify the template to be used as the base. The JIS sample format was withdrawn in 2020 and has largely been replaced by the standard format published by the Ministry of Health, Labour and Welfare, but several formats remain in circulation.

Supporting multiple formats is possible. Templates are held as blank form files, so adding a format is a comparatively minor piece of work.

### A-5. Expected Concurrent Users at Launch (not stated)

Please advise the approximate number of concurrent users expected at launch. This is the basis for server configuration, performance targets, and cost estimates.

### A-6. Staging Environment and Domain (not stated)

Will the staging environment and production domain be provided by your company? If we are to arrange them, additional cost and lead time will apply.

### A-7. Ownership of Terms of Service and Privacy Policy (related to §12)

Because the system handles personal information — names, contact details, employment history — and offers a paid service, Terms of Service and a Privacy Policy are required. Please confirm who is responsible for producing these. We assume this falls outside our scope of work.

---

## 3. [B] Proposals from a Technical Perspective

The following **involve changes to content already written in the specification.** On approval, we will reflect them in the final specification.

### B-1. Limit the Scope of OCR (§5, §10) — *scope change*

The current specification lists "OCR / image analysis" in Section 10 and "OCR-assisted entry" in MVP 3.

**Proposal:** we propose that OCR not be treated as a mandatory requirement at this stage, and that support be limited to **scanned PDFs.**

By way of technical background, there are two kinds of PDF:

| Type | Description | OCR required |
|---|---|---|
| Text-layer PDF | Character data is embedded in the file | **No** — readable directly |
| Scanned PDF | The page is stored as an image of paper | Yes |

Most 履歴書 and 職務経歴書 are the former and can be handled without OCR. We propose that image formats (JPEG / PNG) and handwritten documents be treated as a future extension, as accuracy on those is not consistently reliable.

### B-2. Move Career Advancement Assessment to Expansion (§16) — *scope change*

**Proposal:** we propose that the Career Advancement Assessment in Section 16 be implemented in the Expansion phase rather than in the initial MVPs.

The reason is a dependency. As the specification itself states, this feature operates "after a user completes their resume and work history document," and additionally requires an administrator review-and-edit flow. It therefore **cannot function until both the document creation feature and the admin dashboard are complete.** It is not technically possible to deliver it earlier.

We would also note that this section is numbered 10, duplicating the earlier Section 10. We propose correcting the numbering at the same time.

### B-3. Exclude Social Media Sources from Initial Scope (§3) — *scope change*

**Proposal:** we propose that job data acquisition from social media be **excluded from the initial scope and treated as a future extension**, as the API specifications, terms of use, obtainable scope, and costs of each platform require confirmation first.

As a technical finding: for Facebook, Instagram, and LinkedIn, no means of cross-searching public posts is made available to third parties. For X (formerly Twitter) an acquisition route does exist, but it requires a higher-tier plan, and both the cost and the nature of the obtainable data require separate assessment.

Section 14 of the specification already lists investigation of each platform as a validation item, so we propose deciding this once those results are available.

### B-4. Limit Human Support Channels to In-App Chat (§6) — *closing an open item*

Section 6 states that "Supported channels will be finalized during development." In order to finalize the schedule, we would like to fix the channels for the initial release.

**Proposal:** we propose limiting the initial release to **in-app chat**, with LINE integration as a future extension.

LINE integration requires opening a LINE Official Account, configuring the Messaging API, completing account verification, and — most significantly — **linking the LINE account to the user's account in the web service.** That last item is a feature requiring development, not a configuration step.

With in-app chat, the support agent responds within the conversation the user is already viewing. This reuses the existing conversation infrastructure and keeps additional development to a minimum.

### B-5. Build the Admin Dashboard Incrementally (§8) — *implementation approach*

**Proposal:** rather than building all eight admin functions in Section 8 at once, we propose building them incrementally alongside each MVP.

| Timing | Functions |
|---|---|
| Early MVP | User list, user details |
| Mid MVP | FAQ management, unanswered questions, job acquisition status |
| Later MVP / Expansion | Email history, billing management, audit and security |

Building only the admin functions each MVP requires allows operation to begin earlier and accommodates specification changes more easily.

### B-6. Job Data Acquisition Frequency and Freshness (§3, §11) — *clarification*

The specification defines new-job monitoring as running once per day, but does not state **how often the job data itself is acquired**, nor how the currency of a job is confirmed at the point it is shown to a user.

**Proposal:** we propose separating these into three distinct behaviours.

| Behaviour | Timing | Scope |
|---|---|---|
| **Bulk acquisition** | Weekly, scheduled | All registered sources. Sources matching users' saved search conditions are acquired more frequently on a priority basis |
| **Freshness verification** | At the point of search | Only the small number of jobs about to be presented to the user, and only where the last check is older than a set interval |
| **Manual acquisition** | Administrator-initiated | A specific source, executed as a background job |

**On freshness verification.** Before presenting jobs, the system confirms that those specific postings are still open. This is limited to the jobs actually being shown — typically fewer than ten — so the volume of external access remains proportionate to results displayed rather than to the size of the search. Where a posting can no longer be confirmed as open, it is excluded or marked accordingly.

We would note that verification cannot rely on the HTTP response code alone: many job sites return a normal response for a closed posting and indicate closure only within the page content. Verification therefore requires a per-source check of the page content, which is a small but genuine development item.

**What we do not propose.** We do not propose acquiring job data from external sites at the moment a user asks a question. Searching external sites in real time would make response times unpredictable, and the volume of external access would vary with user behaviour rather than remaining under our control. Acquisition therefore remains scheduled and administrator-managed; what happens at search time is confirmation of jobs already held, not discovery of new ones.

This distinction is consistent with the approach set out in our earlier documentation, in which acquisition and search are separated and the AI is given a job database search function only.

**Related to §11.** The specification already requires that "the freshness of older postings" be made visible using retrieval and update timestamps. We propose displaying the acquisition date on each presented job as standard, in addition to the verification above.

---

## 4. [C] Proposed Additions to the Specification

Items not covered by the current specification that are required for implementation.

### C-1. Add Notifications as a Dedicated Section

Notification behaviour is currently spread across new-job notification (§2-3), the email service (§10), and human support (§6). We propose consolidating it into a dedicated section.

Covering: new-job notifications, delivery of generated documents, human support replies, system notifications, and future LINE integration.

The following also need to be defined:

- The time of day at which the once-daily notification runs
- Whether a notification is sent when there are zero new matches
- Retry handling when a notification fails (§12 mentions retry, but the detail is undefined)

### C-2. Add Account Lifecycle Functions

Section 7 covers only "registration and login." The following are required in practice and each carries implementation effort:

- Password reset
- Email address verification at registration
- Account closure and data deletion

### C-3. Define Job Deduplication in the Data Structure (§4, §11)

Section 11 states "Deduplicate the same job appearing on multiple sources where feasible," but Section 4 contains no corresponding data structure.

**Proposal:** we propose adding to the common fields in Section 4 a distinction between the per-source job ID and a consolidated canonical job ID. Where the same job is posted on several sites, it is held as one job record with multiple sources.

This item carries **the greatest technical difficulty and the least reliable estimate in the project.** The reason is that the same job appears on each site with a different job ID, a different job title, a different rendering of the company name, a different salary unit (monthly vs. annual), and rewritten body text — there is no common identifier by which they can be matched mechanically. The achievable accuracy cannot be assessed until real data is examined, so schedule contingency needs to be allowed for it.

### C-4. Display Behaviour When a Source Fails (§12)

Section 12 states that "If one source stops working or changes specifications, searches against other sources must continue," but does not define what the user is shown when that happens.

For example: whether to display a message such as "Some job sources are currently unavailable." Please confirm.

### C-5. Retention Period for Personal Data (§12)

Section 12 states that retention and deletion policies are required, but **gives no specific period.** Implementation requires a concrete number of days.

Applies to: uploaded 履歴書 and 職務経歴書, generated documents, and conversation history.

---

## 5. [D] Sections We Assess as Requiring No Change

Provided for reference: areas we consider sound from a technical perspective.

| Section | Assessment |
|---|---|
| §1 Product Vision | No change |
| §2-1 AI Interview | No change |
| §9 Permission Design | **No change.** We consider the separation of administrator and human support agent roles should be retained |
| §11 Core AI Rules | No change. All are achievable and appropriate as policy |
| §15 Example UX | No change. This is the clearest statement of intent in the document and is useful as an implementation reference |

---

## 6. Notes

- This document addresses technical confirmation of the specification and does not constitute a legal assessment.
- The permissibility of job data acquisition is being confirmed separately.
- Effort and schedule will be produced once the items in this document have been answered and the final specification is settled.
- Of the validation items in Section 14, "Items to Validate First," we would like to carry out those requiring technical verification using real data.

---

## 7. Next Steps

```
Responses to this document
            ↓
Final specification updated
            ↓
Decisions recorded
            ↓
Development schedule produced
```

We look forward to your confirmation.
