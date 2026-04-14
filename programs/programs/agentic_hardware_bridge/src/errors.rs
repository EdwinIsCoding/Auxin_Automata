use anchor_lang::prelude::*;

#[error_code]
pub enum AuxinError {
    /// Signer does not match the expected key (owner or hardware_pubkey).
    #[msg("Unauthorized: signer does not match expected key")]
    UnauthorizedSigner,

    /// Payment would exceed the agent's lifetime compute budget.
    #[msg("Compute budget exceeded")]
    BudgetExceeded,

    /// Too many transactions in the current rate-limit window.
    #[msg("Rate limit exceeded: too many transactions in current window")]
    RateLimitExceeded,

    /// Provider operation invalid (already exists on add, or not found on remove).
    #[msg("Invalid provider operation")]
    InvalidProvider,

    /// Target provider is not on the agent's whitelist.
    #[msg("Provider is not whitelisted for this agent")]
    ProviderNotWhitelisted,

    /// Compliance event hash exceeds the 64-byte maximum.
    #[msg("Hash exceeds maximum length of 64 bytes")]
    HashTooLong,

    /// Provider whitelist is at maximum capacity (8 entries).
    #[msg("Provider whitelist is full (max 8)")]
    MaxProvidersReached,

    /// Severity must be 0 (DEBUG), 1 (INFO), 2 (WARN), or 3 (CRITICAL).
    #[msg("Invalid severity: must be 0, 1, 2, or 3")]
    InvalidSeverity,

    /// Arithmetic overflow on a checked operation.
    #[msg("Arithmetic overflow")]
    Overflow,

    /// Payment amount must be greater than zero.
    #[msg("Payment amount must be non-zero")]
    ZeroAmount,

    /// Single payment exceeds the per-transaction cap (0.001 SOL).
    #[msg("Per-transaction payment cap exceeded (max 0.001 SOL)")]
    PerTxCapExceeded,
}
