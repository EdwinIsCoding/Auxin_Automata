use anchor_lang::prelude::*;

use crate::errors::AuxinError;
use crate::events::ComplianceEvent;
use crate::state::{ComplianceLog, HardwareAgent, COMPLIANCE_LOG_SPACE, MAX_HASH_LEN};

#[derive(Accounts)]
#[instruction(hash: String, severity: u8, reason_code: u16, slot: u64)]
pub struct LogComplianceEvent<'info> {
    #[account(
        seeds = [b"agent", agent.owner.as_ref()],
        bump = agent.bump,
    )]
    pub agent: Account<'info, HardwareAgent>,

    /// The hardware key signs autonomously — must match agent.hardware_pubkey.
    #[account(
        mut,
        constraint = hardware_signer.key() == agent.hardware_pubkey @ AuxinError::UnauthorizedSigner,
    )]
    pub hardware_signer: Signer<'info>,

    #[account(
        init,
        payer = hardware_signer,
        space = COMPLIANCE_LOG_SPACE,
        seeds = [b"log", agent.key().as_ref(), &slot.to_le_bytes()],
        bump,
    )]
    pub log: Account<'info, ComplianceLog>,

    pub system_program: Program<'info, System>,
}

/// COMPLIANCE CONTRACT: this instruction must NEVER check compute budget,
/// rate-limit windows, or any payment-related state.  See CLAUDE.md.
pub(crate) fn handler(
    ctx: Context<LogComplianceEvent>,
    hash: String,
    severity: u8,
    reason_code: u16,
    _slot: u64,
) -> Result<()> {
    require!(hash.len() <= MAX_HASH_LEN, AuxinError::HashTooLong);
    require!(severity <= 3, AuxinError::InvalidSeverity);

    let clock = Clock::get()?;

    let log = &mut ctx.accounts.log;
    log.agent = ctx.accounts.agent.key();
    log.hash = hash.clone();
    log.severity = severity;
    log.reason_code = reason_code;
    log.timestamp = clock.unix_timestamp;
    log.bump = ctx.bumps.log;

    emit!(ComplianceEvent {
        agent: ctx.accounts.agent.key(),
        hash,
        severity,
        reason_code,
        timestamp: clock.unix_timestamp,
    });

    Ok(())
}
