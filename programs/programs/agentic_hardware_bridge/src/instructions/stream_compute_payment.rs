use anchor_lang::prelude::*;

use crate::errors::AuxinError;
use crate::events::ComputePaymentEvent;
use crate::state::{
    ComputeProvider, HardwareAgent, COMPUTE_PROVIDER_SPACE, MAX_PAYMENT_LAMPORTS,
    RATE_LIMIT_MAX_TXS, RATE_LIMIT_WINDOW_SLOTS,
};

#[derive(Accounts)]
pub struct StreamComputePayment<'info> {
    #[account(
        mut,
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

    /// CHECK: Recipient wallet — validated against agent.providers in the handler.
    #[account(mut)]
    pub provider_wallet: UncheckedAccount<'info>,

    #[account(
        init_if_needed,
        payer = hardware_signer,
        space = COMPUTE_PROVIDER_SPACE,
        seeds = [b"provider", provider_wallet.key().as_ref()],
        bump,
    )]
    pub provider_record: Account<'info, ComputeProvider>,

    pub system_program: Program<'info, System>,
}

pub(crate) fn handler(ctx: Context<StreamComputePayment>, amount_lamports: u64) -> Result<()> {
    require!(amount_lamports > 0, AuxinError::ZeroAmount);
    require!(
        amount_lamports <= MAX_PAYMENT_LAMPORTS,
        AuxinError::PerTxCapExceeded
    );

    let clock = Clock::get()?;
    let provider_key = ctx.accounts.provider_wallet.key();
    let agent_key = ctx.accounts.agent.key();

    // Grab AccountInfo handles for the lamport transfer (before mutable borrows).
    let agent_info = ctx.accounts.agent.to_account_info();
    let provider_wallet_info = ctx.accounts.provider_wallet.to_account_info();

    // ── State checks & updates ────────────────────────────────────────────────

    let agent = &mut ctx.accounts.agent;

    // 1. Provider whitelist
    require!(
        agent.providers.contains(&provider_key),
        AuxinError::ProviderNotWhitelisted
    );

    // 2. Rolling-window rate limit
    if clock
        .slot
        .saturating_sub(agent.last_window_start_slot)
        >= RATE_LIMIT_WINDOW_SLOTS
    {
        agent.last_window_start_slot = clock.slot;
        agent.window_tx_count = 0;
    }
    require!(
        agent.window_tx_count < RATE_LIMIT_MAX_TXS,
        AuxinError::RateLimitExceeded
    );
    agent.window_tx_count = agent
        .window_tx_count
        .checked_add(1)
        .ok_or(error!(AuxinError::Overflow))?;

    // 3. Lifetime budget
    let new_spent = agent
        .lamports_spent
        .checked_add(amount_lamports)
        .ok_or(error!(AuxinError::Overflow))?;
    require!(
        new_spent <= agent.compute_budget_lamports,
        AuxinError::BudgetExceeded
    );
    agent.lamports_spent = new_spent;

    // 4. Update provider record
    let provider_record = &mut ctx.accounts.provider_record;
    if provider_record.provider_pubkey == Pubkey::default() {
        // First payment to this provider — initialize fields.
        provider_record.provider_pubkey = provider_key;
        provider_record.bump = ctx.bumps.provider_record;
    }
    provider_record.total_received = provider_record
        .total_received
        .checked_add(amount_lamports)
        .ok_or(error!(AuxinError::Overflow))?;

    // ── SOL transfer: agent PDA → provider wallet ─────────────────────────────
    // The agent PDA is program-owned, so we debit/credit lamports directly.
    let current = agent_info.lamports();
    **agent_info.try_borrow_mut_lamports()? = current
        .checked_sub(amount_lamports)
        .ok_or(error!(AuxinError::BudgetExceeded))?;

    let prov_current = provider_wallet_info.lamports();
    **provider_wallet_info.try_borrow_mut_lamports()? = prov_current
        .checked_add(amount_lamports)
        .ok_or(error!(AuxinError::Overflow))?;

    // ── Event ─────────────────────────────────────────────────────────────────

    emit!(ComputePaymentEvent {
        agent: agent_key,
        provider: provider_key,
        lamports: amount_lamports,
        timestamp: clock.unix_timestamp,
    });

    Ok(())
}
