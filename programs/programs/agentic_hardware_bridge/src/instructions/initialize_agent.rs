use anchor_lang::prelude::*;
use anchor_lang::system_program;

use crate::events::AgentInitializedEvent;
use crate::state::{HardwareAgent, HARDWARE_AGENT_SPACE};

#[derive(Accounts)]
pub struct InitializeAgent<'info> {
    #[account(
        init,
        payer = owner,
        space = HARDWARE_AGENT_SPACE,
        seeds = [b"agent", owner.key().as_ref()],
        bump,
    )]
    pub agent: Account<'info, HardwareAgent>,

    #[account(mut)]
    pub owner: Signer<'info>,

    pub system_program: Program<'info, System>,
}

pub(crate) fn handler(
    ctx: Context<InitializeAgent>,
    hardware_pubkey: Pubkey,
    compute_budget_lamports: u64,
) -> Result<()> {
    let clock = Clock::get()?;

    let agent = &mut ctx.accounts.agent;
    agent.owner = ctx.accounts.owner.key();
    agent.hardware_pubkey = hardware_pubkey;
    agent.compute_budget_lamports = compute_budget_lamports;
    agent.lamports_spent = 0;
    agent.providers = Vec::new();
    agent.created_at = clock.unix_timestamp;
    agent.last_window_start_slot = 0;
    agent.window_tx_count = 0;
    agent.bump = ctx.bumps.agent;

    // Fund the agent PDA with the compute budget so it can pay providers autonomously.
    // Anchor 1.0: CpiContext::new takes a Pubkey (not AccountInfo).
    system_program::transfer(
        CpiContext::new(
            ctx.accounts.system_program.key(),
            system_program::Transfer {
                from: ctx.accounts.owner.to_account_info(),
                to: ctx.accounts.agent.to_account_info(),
            },
        ),
        compute_budget_lamports,
    )?;

    emit!(AgentInitializedEvent {
        agent: ctx.accounts.agent.key(),
        owner: ctx.accounts.owner.key(),
        hardware_pubkey,
        compute_budget_lamports,
        timestamp: clock.unix_timestamp,
    });

    Ok(())
}
