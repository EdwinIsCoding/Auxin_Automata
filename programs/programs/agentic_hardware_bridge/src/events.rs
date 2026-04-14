use anchor_lang::prelude::*;

/// Emitted by `initialize_agent`.
#[event]
pub struct AgentInitializedEvent {
    pub agent: Pubkey,
    pub owner: Pubkey,
    pub hardware_pubkey: Pubkey,
    pub compute_budget_lamports: u64,
    pub timestamp: i64,
}

/// Emitted by `stream_compute_payment` on every successful transfer.
#[event]
pub struct ComputePaymentEvent {
    pub agent: Pubkey,
    pub provider: Pubkey,
    pub lamports: u64,
    pub timestamp: i64,
}

/// Emitted by `log_compliance_event`.
/// Never dropped — see CLAUDE.md compliance contract.
#[event]
pub struct ComplianceEvent {
    pub agent: Pubkey,
    pub hash: String,
    pub severity: u8,
    pub reason_code: u16,
    pub timestamp: i64,
}

/// Emitted by `update_provider_whitelist`.
#[event]
pub struct ProviderWhitelistUpdatedEvent {
    pub agent: Pubkey,
    pub provider: Pubkey,
    /// true = added, false = removed.
    pub added: bool,
    pub timestamp: i64,
}
