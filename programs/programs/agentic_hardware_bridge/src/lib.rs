use anchor_lang::prelude::*;

pub mod errors;
pub mod events;
pub mod instructions;
pub mod state;

// pub use makes __client_accounts_* types accessible at crate root,
// which the #[program] macro requires for account constraint resolution.
pub use instructions::*;
use state::WhitelistAction;

// Placeholder — replaced by the keypair generated during `anchor build`.
// After first build: copy the printed address here and into Anchor.toml.
declare_id!("7sUSbF9zDN9QKVwA2ZGskg9gFgvbMuQpCdpt3hfgf1Mm");

#[program]
pub mod agentic_hardware_bridge {
    use super::*;

    /// Creates a HardwareAgent PDA and funds it with `compute_budget_lamports`.
    pub fn initialize_agent(
        ctx: Context<InitializeAgent>,
        hardware_pubkey: Pubkey,
        compute_budget_lamports: u64,
    ) -> Result<()> {
        instructions::initialize_agent::handler(ctx, hardware_pubkey, compute_budget_lamports)
    }

    /// Transfers lamports from the agent PDA to a whitelisted provider.
    /// Signed by the hardware key (autonomous). Enforces per-tx cap,
    /// rolling-window rate limit, and lifetime compute budget.
    pub fn stream_compute_payment(
        ctx: Context<StreamComputePayment>,
        amount_lamports: u64,
    ) -> Result<()> {
        instructions::stream_compute_payment::handler(ctx, amount_lamports)
    }

    /// Records an immutable ComplianceLog PDA.
    /// Signed by the hardware key. Never rate-limited or budget-blocked.
    /// `slot` must equal the current slot — used as a PDA seed for uniqueness.
    pub fn log_compliance_event(
        ctx: Context<LogComplianceEvent>,
        hash: String,
        severity: u8,
        reason_code: u16,
        slot: u64,
    ) -> Result<()> {
        instructions::log_compliance_event::handler(ctx, hash, severity, reason_code, slot)
    }

    /// Adds or removes a provider from the HardwareAgent whitelist.
    /// Only the owner authority may call this instruction.
    pub fn update_provider_whitelist(
        ctx: Context<UpdateProviderWhitelist>,
        provider: Pubkey,
        action: WhitelistAction,
    ) -> Result<()> {
        instructions::update_provider_whitelist::handler(ctx, provider, action)
    }
}
