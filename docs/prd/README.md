# PRD Documentation Index

**Project**: Surebet Accounting System
**Version**: v4
**Status**: Draft
**Last Updated**: 2025-10-29

---

## Document Structure

This PRD is organized as a sharded document collection for easier navigation and maintenance.

### Core Documents

1. **[Main PRD](../prd.md)** - Executive summary, functional requirements, and overview
2. **[Data Model](data-model.md)** - Complete database schema and relationships
3. **[Settlement Math](settlement-math.md)** - Exact formulas for settlement and reconciliation
4. **[UI Specification](ui-specification.md)** - Detailed interface layouts and interactions

---

## Quick Navigation

### For Product Managers
- Start with [Main PRD](../prd.md) for overview and functional requirements
- Review [Settlement Math](settlement-math.md) for business logic
- Check [UI Specification](ui-specification.md) for user workflows

### For Developers
- Start with [Data Model](data-model.md) for schema and relationships
- Review [Settlement Math](settlement-math.md) for implementation formulas
- Check [Main PRD](../prd.md) for System Laws (non-negotiable constraints)
- Reference [UI Specification](ui-specification.md) for component requirements

### For QA/Testing
- Review [Main PRD](../prd.md) for acceptance criteria
- Check [Settlement Math](settlement-math.md) for test cases
- Validate against [UI Specification](ui-specification.md) for UI/UX requirements

---

## Key Concepts

### System Laws (Non-Negotiable)
1. **Append-Only Ledger** - Never edit past records, only forward corrections
2. **Frozen FX** - Each ledger row captures its own exchange rate
3. **Equal-Split Settlement** - All participants get equal profit/loss shares
4. **VOID Participation** - VOID bets still participate in settlement splits
5. **Manual Grading** - No automatic sports result detection
6. **No Silent Messaging** - All bot messages require explicit user action

### Core Workflows
1. **Bet Ingestion** → Telegram/Manual → OCR → Approval
2. **Surebet Matching** → Deterministic opposite-side grouping
3. **Settlement** → Grading → Equal-split → Ledger entries
4. **Reconciliation** → NET_DEPOSITS vs SHOULD_HOLD vs CURRENT_HOLDING
5. **Monthly Statements** → Partner-facing profit reports

---

## Glossary

| Term | Definition |
|------|------------|
| **Associate** | Trusted partner who places bets |
| **Surebet** | Arbitrage opportunity with guaranteed profit on two-way market |
| **Two-Way Market** | Over/Under, Yes/No, Team A/Team B |
| **NET_DEPOSITS_EUR** | Cash personally funded by associate |
| **SHOULD_HOLD_EUR** | Entitlement after equal-split settlement |
| **CURRENT_HOLDING_EUR** | Modeled physical holdings |
| **DELTA** | CURRENT_HOLDING - SHOULD_HOLD (over/under holding) |
| **RAW_PROFIT_EUR** | SHOULD_HOLD - NET_DEPOSITS (for monthly statements) |
| **Admin Seat** | Extra equal-split seat for coordinator if they didn't stake |
| **Principal Returned** | Stake returned via WON/VOID bets |
| **Per-Surebet Share** | Equal-split profit/loss per participant |
| **Settlement Batch** | All ledger entries created in one settlement confirm |
| **FX Snapshot** | Frozen exchange rate captured at ledger entry creation |

---

## Document Change History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| v4 | 2025-10-29 | John (PM Agent) | Initial PRD creation from final-project.md |

---

## Related Documents

- [Source Specification](../../Final-Project.md) - Original detailed specification
- [Architecture Documentation](../../architecture.md) - Technical architecture (if exists)

---

## Feedback & Questions

For questions or clarifications about this PRD:
1. Review the relevant section in the appropriate document
2. Check if your question is addressed in [Settlement Math](settlement-math.md) or [Data Model](data-model.md)
3. Consult the [Source Specification](../../Final-Project.md) for additional context

---

**End of PRD Index**
