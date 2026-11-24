# Wallet-key exposure incident — 2026-11-25

## Finding

The default branch contained wallet signing material in tracked `.env`, `owner.env`, `bot1.env` and `bot2.env` files. Values are intentionally not reproduced here. The tracked values were classified as non-placeholder private-key material during a metadata-only review; no key value is copied into this report.

## Repository-side remediation in this branch

- Removes all four tracked secret files from the branch tree.
- Adds ignore rules for `.env*`, wallet files, key/seed/mnemonic artifacts and local build outputs.
- Replaces `.env.example` with a non-secret template.
- Updates wallet loaders to prefer `OWNER_PRIVATE_KEY`, `BOT1_PRIVATE_KEY` and `BOT2_PRIVATE_KEY` environment variables; ignored local files remain an optional development fallback.
- Does not rewrite Git history.

## Mandatory external incident response

Treat every previously committed wallet key as compromised. Before any deployment or transaction:

1. Identify the corresponding addresses and every chain/account where each key was used.
2. Revoke/transfer all owner, admin, minter, operator and bot permissions to independently generated replacement wallets.
3. Move remaining assets only after verifying chain IDs and destination addresses through an independent channel.
4. Revoke token allowances and other delegated permissions where applicable.
5. Review on-chain activity, RPC/provider logs, CI logs, local backups and access records for unauthorized use.
6. Confirm each old key has no remaining privileged role and cannot sign an accepted operation.
7. Plan Git-history sanitization with all collaborators; current-tree deletion alone does not remove historical copies.
8. Record only public addresses, transaction hashes and rotation attestations here. Never record private material.

## Evidence boundary

This branch demonstrates repository-side deletion and safer key-loading paths only. It does **not** prove that any wallet was rotated, any authority was revoked, assets are safe, or Git history was purged. Until external evidence is supplied and reviewed, deployment remains blocked.
