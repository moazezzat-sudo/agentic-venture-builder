> **STUBBED**: this output comes from a stubbed step, not a working feature.

# Phase 6, step 1: metrics, persevere-or-pivot memo and support replies

Draft for the founder to review and approve. Every claim shows its support: a source URL with its tier, our own evidence, or ASSUMPTION.

> **MOCKED data**: there are no real customers or sales. These numbers come from `payments.mock_sales_data() (MOCKED)` and can't support a real decision.

## Metrics

Amounts in minor units of EGP.

| Metric | Value |
|---|---|
| orders | 6 |
| paid_orders | 4 |
| refunded_orders | 1 |
| conversion_rate | 0.667 |
| refund_rate | 0.25 |
| gross | 100000 |
| fees | 3000 |
| refunds | 25000 |
| net | 72000 |
| reconciled | True |
| currency | EGP |

## Against the targets set at Gate 2

| Metric | Target | Actual | Result |
|---|---|---|---|
| paid_orders | at least 10 | 4 | **missed** |

## Recommendation (fixed rules, not the model)

**REPEAT**: The data is MOCKED: fake sales can't support persevere or pivot. Collect real sales first.

The founder approves or rejects this at the Gate 6 decision.

## Memo

Metrics are mocked and cannot be used for real strategic decisions.

### Observations

- All sales figures are flagged as fake, so they do not reflect actual market performance. (on MOCKED data) (ASSUMPTION)
- Target of 10 paid orders is unmet, but the gap cannot be evaluated due to mock data. (on MOCKED data) (ASSUMPTION)
- Recommendation to repeat is based solely on the disclaimer that data is not real. (on MOCKED data) (ASSUMPTION)

### Next experiments

- Launch a limited pilot with real customers to capture authentic order and conversion data.
- Implement a tracking system to record actual payments, refunds, and net revenue.
- Set up a small‑scale marketing test to measure genuine conversion rates against the waitlist target.

## Support-reply drafts (not sent)

The founder edits and sends these under their own name, and decides every refund in their own payment provider.

### Customer requesting a refund

Hi [Customer Name], I’m sorry to hear you’re not satisfied with your purchase. I’ve initiated the refund process on our end and will keep you updated as it progresses. Please allow a few business days for the amount to appear on your statement. If there’s anything else I can help with, feel free to let me know. Best regards, [Founder Name]

### Customer unable to access the product

Hi [Customer Name], Thank you for reaching out. I’m sorry you’re experiencing access issues. Could you please share the error message you’re seeing and the device you’re using? I’ll investigate immediately and get back to you with a solution. Appreciate your patience. Best, [Founder Name]


## Claims

0. orders: 6 (MOCKED) (metrics; our evidence: payments.mock_sales_data() (MOCKED))
1. paid_orders: 4 (MOCKED) (metrics; our evidence: payments.mock_sales_data() (MOCKED))
2. refund_rate: 0.25 (MOCKED) (metrics; our evidence: payments.mock_sales_data() (MOCKED))
3. net: 72000 (MOCKED) (metrics; our evidence: payments.mock_sales_data() (MOCKED))
4. All sales figures are flagged as fake, so they do not reflect actual market performance. (on MOCKED data) (observation; ASSUMPTION)
5. Target of 10 paid orders is unmet, but the gap cannot be evaluated due to mock data. (on MOCKED data) (observation; ASSUMPTION)
6. Recommendation to repeat is based solely on the disclaimer that data is not real. (on MOCKED data) (observation; ASSUMPTION)

## Guardrail check

None: every text in this draft passed `guardrails.check_text`.
