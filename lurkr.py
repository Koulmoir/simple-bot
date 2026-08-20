import asyncio
import time
from asyncio import CancelledError
from http.client import HTTPException
from typing import Optional, Callable, Sequence
from loguru import logger

import aiohttp
import discord
from discord import VoiceChannel, guild, Guild, TextChannel
from discord.ext.commands import Bot

_log = logger

_base_url = 'https://api.lurkr.gg/v2/'
_tasks = []
_sesh = None
_xp_gain_bonus = {}

def _get_vcs(guilds: Sequence[Guild]) -> Sequence[VoiceChannel]:
    vcs: list[VoiceChannel] = []
    for guild in guilds:
        for channel in guild.channels:
            if isinstance(channel, VoiceChannel):
                vcs.append(channel)
    return vcs

async def _get_guilds(guilds: list[int], susannaClient: Bot) -> Sequence[Guild] | None:
    guild_collection = [
        guild_real
        for guild in guilds
        if (guild_real := susannaClient.get_guild(guild)) is not None
    ]
    return guild_collection if len(guild_collection) > 0 else None

def _filter_vc(afk: bool, vcs: Sequence[VoiceChannel]) -> Sequence[VoiceChannel] | None:
    if not afk:
        return vcs
    new_collection = [channel for channel in vcs if not channel.name.startswith("AFK")]
    return new_collection if len(new_collection) > 0 else None


def _build_id_list(vc: VoiceChannel):
    _log.debug(f"Building member list for channel: {vc.name} ({vc.id})")
    return [
        member for member in vc.members
        if not (member.voice.mute or member.voice.self_mute)
    ]

async def _upd_xp(
        sesh,
        guild_id,
        member_id,
        xp,
):
    data = {"xp":{"increment":xp}}
    api_url = f'levels/{guild_id}/users/{member_id}'
    _log.debug(f"Attempting to send PATCH with data: {data} ({api_url})")
    result = await sesh.patch(url=api_url, json=data)
    if result.status == 200:
        _log.debug("PATCH request success to lurkr")
        return
    if result.status == 429:
        json = await result.json()
        cooldown = float(json["Retry-After"])
        _log.warning(f"Failed initial PATCH retying in : {cooldown} seconds")
        await asyncio.sleep(cooldown)
        result = await sesh.post(f'/levels/{guild_id}/users/{member_id}', data=data)
        if result.status == 200:
            return
        else:
            ex = HTTPException()
            ex.add_note("Lurkr has shadow banned us due to api calls, cancelling.")
            raise ex
    else:
        _log.warning(f"Failed with status code: {result.status} ({await result.text()})")
    return


async def _safely_check_update(
        voice_channel: VoiceChannel,
        tick: int,
        xp: int,
        sesh,
        logChannel: TextChannel
):
    try:
        while True:
            if not voice_channel:
                _log.error("Voice channel does not exist!")
                return

            start = time.time()
            member_list = _build_id_list(voice_channel)
            _log.debug(
                f'Users found in channel {voice_channel.name} ({voice_channel.id}): {len(member_list)}'
            )
            guild_id = voice_channel.guild.id

            for member_id in member_list:
                await logChannel.send(
                    content=f"Updated xp for: {member_id}"
                )
                await _upd_xp(
                    guild_id=guild_id,
                    member_id=member_id,
                    xp=xp,
                    sesh=sesh
                )

            diff = time.time() - start
            sleep_time = max(0, tick - diff)
            await asyncio.sleep(sleep_time)

    except asyncio.CancelledError:
        _log.info(f"Lurkr task for VC {voice_channel.name} cancelled")
        raise



async def _run_main(
        *,
        susannaClient: Bot,
        lurkr_token: str,
        afk: bool,
        tick: int,
        xp: int,
        guilds: Optional[list[int]],
):
    global _tasks, _sesh
    try:

        _log.info("Starting lurkr...")
        _log.debug("Starting lurkr connection")
        _sesh = aiohttp.ClientSession(
            base_url=_base_url,
            headers={
                "X-API-KEY": f'{lurkr_token}'
            }
        )
        _log.debug("Getting guilds")
        guild_collection = await _get_guilds(guilds=guilds, susannaClient=susannaClient) if guilds else susannaClient.guilds
        if not guild_collection:
            ex = ValueError()
            ex.add_note("Guild id table given but no guilds found!")
            raise ex
        _log.debug(f"Getting vcs for {len(guild_collection)} guilds")
        vc_collection = _get_vcs(guild_collection)
        _log.debug(f"Got {len(vc_collection)} unfiltered vc's")
        filtered_vcs = _filter_vc(afk,vc_collection)
        if not filtered_vcs:
            ex = ValueError()
            ex.add_note("All VC's found are afk")
            raise ex
        _log.debug(f"Got {len(filtered_vcs)} filtered vc")
        log_channel = susannaClient.get_channel(1539970407115919470)
        if not isinstance(log_channel, TextChannel):
            return
        _tasks = [
            asyncio.create_task(_safely_check_update(
            voice_channel=vc,
            tick=tick,
            xp=xp,
            sesh=_sesh,
            logChannel=log_channel
        )) for vc in filtered_vcs]
        _log.info("Started lurkr!")
        await asyncio.Event().wait()

    except (KeyboardInterrupt, CancelledError):
        _log.info("Cleaning up lurkr...")
        for task in _tasks:
            task.cancel()

        if _tasks:
            await asyncio.gather(*_tasks, return_exceptions=True)
        await _sesh.close()
        _log.info("Closed all lurkr tasks.")
        raise
    except Exception as e:
        _log.error(f"Lurkr failed due to error: {e}")


def run_main_lurkr(
        *,
        susannaClient: Bot,
        lurkr_token: str,
        afk: bool,
        tick: int,
        xp: int,
        guilds: Optional[list[int]],
) -> Callable[[], None]:
    """
    Will start the lurkr Vc cycle, will stop when returning function is called.

    :param susannaClient: The botClient, make sure it's connected! (don't ask about the name)
    :param lurkr_token: The lurkr api token of the given guilds
    :param afk: Look for channels called "afk" (These channels will not count towards xp)
    :param tick: How many seconds to wait between each lookup
    :param xp: How much xp should be earned per tick
    :param guilds: (Optional) Uses all guilds the bot is in by default
    :return: The function that will stop the cycle once called
    """

    task = asyncio.create_task(_run_main(
        susannaClient=susannaClient,
        lurkr_token=lurkr_token,
        afk=afk,
        tick=tick,
        xp=xp,
        guilds=guilds
    ))

    def close():
        """
        Stops the current lurkr vc loop

        :return: Nothing
        """
        task.cancel()
        return

    return close
