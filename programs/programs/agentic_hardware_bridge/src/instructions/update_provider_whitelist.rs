use anchor_lang::prelude::*;

use crate::errors::AuxinError;
use crate::events::ProviderWhitelistUpdatedEvent;
use crate::state::{HardwareAgent, WhitelistAction, MAX_PROVIDERS};

#[derive(Accounts)]
pub struct UpdateProviderWhitelist<'info> {
    #[account(
        mut,
        seeds = [b"agent", owner.key().as_ref()],
        bump = agent.bump,
        has_one = owner @ AuxinError::UnauthorizedSigner,
    )]
    pub agent: Account<'info, HardwareAgent>,

    /// Only the owner authority may modify the whitelist.
    pub owner: Signer<'info>,
}

pub(crate) fn handler(
    ctx: Context<UpdateProviderWhitelist>,
    provider: Pubkey,
    action: WhitelistAction,
) -> Result<()> {
    let agent = &mut ctx.accounts.agent;

    match action {
        WhitelistAction::Add => {
            require!(
                !agent.providers.contains(&provider),
                AuxinError::InvalidProvider
            );
            require!(agent.providers.len() < MAX_PROVIDERS, AuxinError::MaxProvidersReached);
            agent.providers.push(provider);
        }
        WhitelistAction::Remove => {
            let idx = agent
                .providers
                .iter()
                .position(|p| *p == provider)
                .ok_or(error!(AuxinError::InvalidProvider))?;
            agent.providers.swap_remove(idx);
        }
    }

    let added = action == WhitelistAction::Add;

    emit!(ProviderWhitelistUpdatedEvent {
        agent: ctx.accounts.agent.key(),
        provider,
        added,
        timestamp: Clock::get()?.unix_timestamp,
    });

    Ok(())
}
