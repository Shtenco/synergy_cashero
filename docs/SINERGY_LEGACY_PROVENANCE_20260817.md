# Cashero legacy provenance in the SINERGY lineage

Status: additive provenance document. Existing robots, simulations, contracts, deployment scripts and historical reports remain unchanged.

## Historical role

`Shtenco/cashero` is an important ancestor of later SINERGY liquidity and adaptive-supply research.

The repository contains research lines around:

- cyclic multi-wallet actions;
- sequential buying and partial profit-taking;
- liquidity reinvestment;
- adaptive mint/burn behavior;
- CASRS/WMATIC and CASRG/WMATIC pool experiments;
- Polygon multi-RPC live robot infrastructure;
- exact and aggregate-asset simulations;
- V3 contract/deploy/liquidity/bot packaging.

## What should be preserved

All of the above remains useful as historical evidence for how later ideas evolved:

```text
cyclic scheduling
 -> liquidity reinvestment
 -> adaptive supply
 -> protocol-owned-liquidity research
 -> EAMM / graph-liquidity research
 -> later Financial OS accounting corrections
```

## What should not be inferred

The existence of a cyclic robot, rising token price, liquidity addition or internal portfolio mark does not by itself establish consolidated external profit under current SINERGY accounting.

Current canonical interpretation is owned by `synergy_financial_os` / relevant Financial OS reference layers and requires external-value accounting.

## Evidence status

Treat the repository as `LEGACY` with individual experiments potentially carrying stronger execution/simulation evidence. Do not upgrade the entire repository to a production financial claim.

## Migration rule

If a mechanism is reused later, reference the exact Cashero source file/commit and adapt it additively. Do not delete the original or rewrite its historical assumptions.

Examples of potentially reusable engineering ideas:

- cyclic scheduling/state machines;
- multi-RPC resilience patterns;
- simulation harnesses;
- LP reinvestment plumbing;
- adaptive parameter testing.

Economic claims must be revalidated under the current canonical balance-sheet and external-settlement rules.

## Security boundary

Historical live-trading scripts that can sign/send transactions remain high-risk operational artifacts. Their presence in the lineage does not imply they should be reused with historical keys, balances or configuration. Future reuse requires fresh security review and explicit deployment authorization.
