import asyncio
import os

from dotenv import load_dotenv
from discord.ext.commands import Bot
from discord import LoginFailure, HTTPException, GatewayNotFound, Client, Intents
from logging import getLogger

from lurkr import run_main_lurkr

logger = getLogger("Main")
load_dotenv()

max_retry = 3
retry_CD_s = 20
close = None

token = os.getenv("BOT_TOKEN")
lurkr_token = os.getenv("LURKR_API_TOKEN")

async def retry(token: str, max_retry, wait, client: Client):
    tries = 0
    logger.info(f"Starting Attempt {tries+1} for bot start...")
    logger.debug(f"max_retry = {max_retry}, client.is_closed() = {client.is_closed()}")
    while tries < max_retry:
        try:
            await client.start(
                token=token,
                reconnect=True
            )
            break
        except LoginFailure:
            logger.error("Token not valid! Aborting...")
        except HTTPException:
            logger.error("HTTP Error during startup! Aborting...")
        except GatewayNotFound:
            logger.error("Discord down, wrap it up")
        finally:
            if client.is_closed():
                tries+=1
                if tries < max_retry:
                    logger.debug(f"Restarting in {wait} secs...")
                    await asyncio.sleep(wait)
                else:
                    logger.error("Max retries reached, aborting...")


async def startBot(token: str, client: Bot) ->  None:
    global max_retry, retry_CD_s
    max_retry = max_retry
    wait = retry_CD_s
    await retry(
        token=token,
        max_retry=max_retry,
        wait=wait,
        client=client
    )
    if client.is_closed():
        logger.error("Client disconnected")

async def _run():
    global close
    try:
        intent = Intents.all()
        botClient = Bot(
            command_prefix="./",
            intents=intent
        )
        if not token:
            return
        if not lurkr_token:
            return
        await startBot(token, botClient)
        close = run_main_lurkr(
            susannaClient=botClient,
            lurkr_token=lurkr_token,
            tick=30,
            afk=False,
            xp=8,
            guilds=[1532717797292113971]
        )
    except Exception:
        close()


if __name__ == '__main__':
    Bot_task = asyncio.create_task(_run())
