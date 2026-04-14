use anchor_lang::prelude::*;

// ── Space constants ───────────────────────────────────────────────────────────
// Each constant includes the 8-byte Anchor discriminator.

/// 8 + 32 + 32 + 8 + 8 + (4 + 8×32) + 8 + 8 + 2 + 1 = 367
pub const HARDWARE_AGENT_SPACE: usize = 367;

/// 8 + 32 + 8 + 1 = 49
pub const COMPUTE_PROVIDER_SPACE: usize = 49;

/// 8 + 32 + (4 + 64) + 1 + 2 + 8 + 1 = 120
pub const COMPLIANCE_LOG_SPACE: usize = 120;

// ── Constants ─────────────────────────────────────────────────────────────────

pub const MAX_PROVIDERS: usize = 8;
pub const MAX_HASH_LEN: usize = 64;

/// Rolling-window rate limit: max transactions per window.
pub const RATE_LIMIT_MAX_TXS: u16 = 100;

/// Rolling-window rate limit: window size in slots (~60 slots ≈ 24s on mainnet).
pub const RATE_LIMIT_WINDOW_SLOTS: u64 = 60;

/// Per-transaction payment cap: 0.001 SOL = 1_000_000 lamports.
pub const MAX_PAYMENT_LAMPORTS: u64 = 1_000_000;

// ── Enums ─────────────────────────────────────────────────────────────────────

#[derive(AnchorSerialize, AnchorDeserialize, Clone, PartialEq, Eq, Debug)]
pub enum WhitelistAction {
    Add,
    Remove,
}

// ── HardwareAgent ─────────────────────────────────────────────────────────────

/// PDA representing a registered autonomous hardware agent.
///
/// Seeds: `[b"agent", owner.key().as_ref()]`
#[account]
#[derive(Debug)]
pub struct HardwareAgent {
    /// Wallet authority — must sign init and whitelist-update instructions.
    pub owner: Pubkey,

    /// Ed25519 key burned into the hardware module.
    /// Signs autonomous payment and compliance instructions.
    pub hardware_pubkey: Pubkey,

    /// Lifetime cap on compute payments (lamports).
    /// Also the SOL deposited into this PDA at init time.
    pub compute_budget_lamports: u64,

    /// Running total of lamports disbursed via stream_compute_payment.
    pub lamports_spent: u64,

    /// Whitelisted compute providers; max `MAX_PROVIDERS` (8) entries.
    pub providers: Vec<Pubkey>,

    /// Unix timestamp at account creation.
    pub created_at: i64,

    /// Slot at which the current rate-limit window began.
    pub last_window_start_slot: u64,

    /// Transactions counted in the current rate-limit window.
    pub window_tx_count: u16,

    /// Canonical PDA bump.
    pub bump: u8,
}

// ── ComputeProvider ───────────────────────────────────────────────────────────

/// PDA tracking aggregate lamports received by a compute provider.
///
/// Seeds: `[b"provider", provider_pubkey.as_ref()]`
/// Initialized lazily on first payment to a new provider.
#[account]
#[derive(Debug)]
pub struct ComputeProvider {
    pub provider_pubkey: Pubkey,
    pub total_received: u64,
    pub bump: u8,
}

// ── ComplianceLog ─────────────────────────────────────────────────────────────

/// Immutable on-chain record of a compliance event.
///
/// Seeds: `[b"log", agent.key().as_ref(), &slot.to_le_bytes()]`
#[account]
#[derive(Debug)]
pub struct ComplianceLog {
    /// The HardwareAgent that triggered this event.
    pub agent: Pubkey,

    /// Keccak-256 hex digest of the raw telemetry payload (max 64 chars).
    pub hash: String,

    /// Severity level: 0 = DEBUG, 1 = INFO, 2 = WARN, 3 = CRITICAL.
    pub severity: u8,

    /// Application-defined reason code (e.g. 0x0001 = torque-limit).
    pub reason_code: u16,

    /// Unix timestamp from Clock.
    pub timestamp: i64,

    /// Canonical PDA bump.
    pub bump: u8,
}
