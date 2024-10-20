import asyncio
from datetime import datetime, timedelta
import random
from urllib.parse import unquote

import aiohttp
from aiohttp_proxy import ProxyConnector
from better_proxy import Proxy
from pyrogram import Client
from pyrogram.errors import Unauthorized, UserDeactivated, AuthKeyUnregistered, FloodWait
from pyrogram.raw.functions import account, messages
import time
import re
import json
from pyrogram.raw.types import InputBotAppShortName, InputNotifyPeer, InputPeerNotifySettings
import pytz
from tzlocal import get_localzone
from .agents import generate_random_user_agent
from bot.config import settings
from typing import Callable
import functools
from bot.utils import logger
from bot.exceptions import InvalidSession
from .headers import headers


global_answers = {}

# async def update_answers_periodically():
#     global global_answers
#     while True:
#         with open('answers.json', 'r') as file:
#             global_answers = json.load(file)
#         await asyncio.sleep(7200)  # Sleep for 2 hours

# async def initialize_background_tasks():
#     asyncio.create_task(update_answers_periodically())

def error_handler(func: Callable):
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            await asyncio.sleep(1)
    return wrapper

def is_puzzle_expired(expiration_time_utc_str):
    local_tz = get_localzone()
    utc_tz = pytz.utc
    expiration_time_utc = datetime.strptime(expiration_time_utc_str, '%Y-%m-%d %I:%M %p')
    expiration_time_utc = utc_tz.localize(expiration_time_utc)
    expiration_time_local = expiration_time_utc.astimezone(local_tz)
    current_time = datetime.now(local_tz)
    return current_time >= expiration_time_local

def convert_date_format(date_str):
    """
    Converts a date from DD-MM-YYYY format to YYYY-MM-DD format.
    """
    try:
        date_obj = datetime.strptime(date_str, '%d-%m-%Y')
        increased_date_obj = date_obj + timedelta(days=1)
        return increased_date_obj.strftime('%Y-%m-%d')
    except ValueError:
        return None

class Tapper:
    def __init__(self, tg_client: Client, proxy: str):
        self.tg_client = tg_client
        self.session_name = tg_client.name
        self.proxy = proxy
        self.tg_web_data = None
        self.tg_client_id = 0
        
    async def get_tg_web_data(self) -> str:
        
        if self.proxy:
            proxy = Proxy.from_str(self.proxy)
            proxy_dict = dict(
                scheme=proxy.protocol,
                hostname=proxy.host,
                port=proxy.port,
                username=proxy.login,
                password=proxy.password
            )
        else:
            proxy_dict = None

        self.tg_client.proxy = proxy_dict

        try:
            if not self.tg_client.is_connected:
                try:
                    await self.tg_client.connect()

                except (Unauthorized, UserDeactivated, AuthKeyUnregistered):
                    raise InvalidSession(self.session_name)
            
            while True:
                try:
                    peer = await self.tg_client.resolve_peer('major')
                    break
                except FloodWait as fl:
                    fls = fl.value

                    logger.warning(f"{self.session_name} | FloodWait {fl}")
                    logger.info(f"{self.session_name} | Sleep {fls}s")
                    await asyncio.sleep(fls + 3)
            
            ref_id = settings.REF_ID if random.randint(0, 100) <= 70 else "916734478"
            
            web_view = await self.tg_client.invoke(messages.RequestAppWebView(
                peer=peer,
                app=InputBotAppShortName(bot_id=peer, short_name="start"),
                platform='android',
                write_allowed=True,
                start_param=ref_id
            ))

            auth_url = web_view.url
            tg_web_data = unquote(string=auth_url.split('tgWebAppData=')[1].split('&tgWebAppVersion')[0])

            me = await self.tg_client.get_me()
            self.tg_client_id = me.id
            
            if self.tg_client.is_connected:
                await self.tg_client.disconnect()

            return ref_id, tg_web_data

        except InvalidSession as error:
            logger.error(f"{self.session_name} | Invalid session")
            await asyncio.sleep(delay=3)
            return None, None

        except Exception as error:
            logger.error(f"{self.session_name} | Unknown error: {error}")
            await asyncio.sleep(delay=3)
            return None, None
        
    @error_handler
    async def join_and_mute_tg_channel(self, link: str):
        await asyncio.sleep(delay=random.randint(15, 30))
        
        if not self.tg_client.is_connected:
            await self.tg_client.connect()

    
            parsed_link = link if 'https://t.me/+' in link else link[13:]
            
            chat = await self.tg_client.get_chat(parsed_link)

            if chat.username:
                chat_username = chat.username
            elif chat.id:
                chat_username = chat.id
            else:
                logger.info("Unable to get channel username or id")
                return

            logger.info(f"{self.session_name} | Retrieved channel: <y>{chat_username}</y>")
            try:
                try:
                    await self.tg_client.get_chat_member(chat_username, "me")
                    logger.info(f"{self.session_name} | Already a member of chat <y>{chat_username}</y>")
                except Exception as error:
                    if hasattr(error, 'ID') and error.ID == 'USER_NOT_PARTICIPANT':
                        await asyncio.sleep(delay=3)
                        chat = await self.tg_client.join_chat(parsed_link)
                        chat_id = chat.id
                        logger.info(f"{self.session_name} | Successfully joined chat <y>{chat_username}</y>")
                        await asyncio.sleep(random.randint(5, 10))
                        peer = await self.tg_client.resolve_peer(chat_id)
                        await self.tg_client.invoke(account.UpdateNotifySettings(
                            peer=InputNotifyPeer(peer=peer),
                            settings=InputPeerNotifySettings(mute_until=2147483647)
                        ))
                        logger.info(f"{self.session_name} | Successfully muted chat <y>{chat_username}</y>")
                    else:
                        logger.error(f"{self.session_name} | Error while checking channel: <y>{chat_username}</y>: {str(error.ID)}")
            except Exception as e:
                logger.error(f"{self.session_name} | Error joining/muting channel {link}: {str(e)}")
                await asyncio.sleep(delay=3)
            finally:
                if self.tg_client.is_connected:
                    await self.tg_client.disconnect()
                await asyncio.sleep(random.randint(10, 20))
    
    @error_handler
    async def make_request(self, http_client, method, endpoint=None, url=None, **kwargs):
        full_url = url or f"https://major.bot/api{endpoint or ''}"
        response = await http_client.request(method, full_url, **kwargs)
        response.raise_for_status()
        return await response.json()
    
    @error_handler
    async def login(self, http_client, init_data, ref_id):
        response = await self.make_request(http_client, 'POST', endpoint="/auth/tg/", json={"init_data": init_data})
        if response and response.get("access_token", None):
            return response
        return None
    
    @error_handler
    async def get_daily(self, http_client):
        return await self.make_request(http_client, 'GET', endpoint="/tasks/?is_daily=true")
    
    @error_handler
    async def get_tasks(self, http_client):
        return await self.make_request(http_client, 'GET', endpoint="/tasks/?is_daily=false")
    
    @error_handler
    async def done_tasks(self, http_client, task_id):
        return await self.make_request(http_client, 'POST', endpoint="/tasks/", json={"task_id": task_id})
    
    @error_handler
    async def claim_swipe_coins(self, http_client):
        response = await self.make_request(http_client, 'GET', endpoint="/swipe_coin/")
        if response and response.get('success') is True:
            logger.info(f"{self.session_name} | Start game <y>SwipeCoins</y>")
            coins = random.randint(settings.SWIPE_COIN[0], settings.SWIPE_COIN[1])
            payload = {"coins": coins }
            await asyncio.sleep(55)
            response = await self.make_request(http_client, 'POST', endpoint="/swipe_coin/", json=payload)
            if response and response.get('success') is True:
                return coins
            return 0
        return 0

    @error_handler
    async def claim_hold_coins(self, http_client):
        response = await self.make_request(http_client, 'GET', endpoint="/bonuses/coins/")
        if response and response.get('success') is True:
            logger.info(f"{self.session_name} | Start game <y>HoldCoins</y>")
            coins = random.randint(settings.HOLD_COIN[0], settings.HOLD_COIN[1])
            payload = {"coins": coins }
            await asyncio.sleep(55)
            response = await self.make_request(http_client, 'POST', endpoint="/bonuses/coins/", json=payload)
            if response and response.get('success') is True:
                return coins
            return 0
        return 0

    @error_handler
    async def claim_roulette(self, http_client):
        response = await self.make_request(http_client, 'GET', endpoint="/roulette/")
        if response and response.get('success') is True:
            logger.info(f"{self.session_name} | Start game <y>Roulette</y>")
            await asyncio.sleep(10)
            response = await self.make_request(http_client, 'POST', endpoint="/roulette/")
            if response:
                return response.get('rating_award', 0)
            return 0
        return 0
    
    @error_handler
    async def visit(self, http_client):
        return await self.make_request(http_client, 'POST', endpoint="/user-visits/visit/?")
        
    @error_handler
    async def streak(self, http_client):
        return await self.make_request(http_client, 'POST', endpoint="/user-visits/streak/?")
    
    @error_handler
    async def get_detail(self, http_client):
        detail = await self.make_request(http_client, 'GET', endpoint=f"/users/{self.tg_client_id}/")
        
        return detail.get('rating') if detail else 0
    
    @error_handler
    async def leave_squad(self, http_client):
        return await self.make_request(http_client, 'POST', endpoint=f"/squads/leave/?")
    
    @error_handler
    async def join_squad(self, http_client, squad_id):
        return await self.make_request(http_client, 'POST', endpoint=f"/squads/{squad_id}/join/?")
    
    @error_handler
    async def get_squad(self, http_client, squad_id):
        return await self.make_request(http_client, 'GET', endpoint=f"/squads/{squad_id}?")
    
    @error_handler
    async def get_puzzle_answer(self):
        async with aiohttp.ClientSession() as session:
            async with session.get("https://raw.githubusercontent.com/yanpaing007/MajorBot/refs/heads/main/answers.json") as response:
                try:
                       
                        if response.status != 200:
                            logger.error(f"{self.session_name} | Failed to get puzzle answer: {response.status}")
                            return None
                        text = await response.text()
                        data = json.loads(text)
                        expire = data.get('expires', 0)
                        
                        if is_puzzle_expired(expire):
                            logger.info(f"{self.session_name} | The puzzle has expired. Retrying from backup puzzle repo...")
                        
                            async with session.get("https://raw.githubusercontent.com/zuydd/database/refs/heads/main/major.json") as backup_response:
                                if backup_response.status != 200:
                                    logger.error(f"{self.session_name} | Failed to get backup puzzle answer: {backup_response.status}")
                                    return None
                                text = await backup_response.text()
                                backup_data = json.loads(text)
                                durov_data = backup_data.get('durov', {})
                                puzzle_day_str = durov_data.get('day', None)
                                puzzle = durov_data.get('answer', [])

                                if not puzzle_day_str or not puzzle:
                                    logger.error("Invalid backup puzzle data.")
                                    return None
                                
                                puzzle_day_str = convert_date_format(puzzle_day_str)
                                if puzzle_day_str:
                                    puzzle_day_str += " 12:00 AM"  
                                    if is_puzzle_expired(puzzle_day_str):
                                        logger.info(f"{self.session_name} | The backup puzzle has expired too.")
                                        return None
                                
                                    payload = {
                                        "choice_1": puzzle[0],
                                        "choice_2": puzzle[1],
                                        "choice_3": puzzle[2],
                                        "choice_4": puzzle[3],
                                    }
                                    logger.info(f"{self.session_name} | Backup puzzle retrieved successfully: {puzzle}")
                                    return payload
                                
                                logger.error("Invalid date format in backup puzzle day.")
                                return None

                        puzzle = data.get('answer', {})
                        logger.info(f"{self.session_name} | Puzzle retrieved successfully: {puzzle}")
                        return puzzle
                except Exception as e:
                    return None
        
        
    
    @error_handler
    async def youtube_answers(self, http_client, task_id, task_title):
        async with aiohttp.ClientSession() as session:
            async with session.get("https://raw.githubusercontent.com/yanpaing007/MajorBot/refs/heads/main/answers.json") as response:
                status = response.status
                if status == 200:
                    response_data = json.loads(await response.text())
                    youtube_answers = response_data.get('youtube', {})
                    if task_title in youtube_answers:
                        answer = youtube_answers[task_title]
                        payload = {
                            "task_id": task_id,
                            "payload": {
                                "code": answer
                            }
                        }
                        logger.info(f"{self.session_name} | Attempting YouTube task: <y>{task_title}</y>")
                        response = await self.make_request(http_client, 'POST', endpoint="/tasks/", json=payload)
                        if response and response.get('is_completed') is True:
                            logger.info(f"{self.session_name} | Completed YouTube task: <y>{task_title}</y>")
                            return True
        return False
    
    
    @error_handler
    async def puvel_puzzle(self, http_client):
        puzzle_answer = await self.get_puzzle_answer()
        if puzzle_answer is not None:
            start = await self.make_request(http_client, 'GET', endpoint="/durov/")
            if start and start.get('success', False):
                logger.info(f"{self.session_name} | Started game <y>Puzzle</y>")
                await asyncio.sleep(random.randint(5, 7))
                
                # Send the puzzle answer
                result = await self.make_request(http_client, 'POST', endpoint="/durov/", json=puzzle_answer)
                if result:
                    logger.info(f"{self.session_name} | Puzzle submitted successfully.")
                    return result
                else:
                    logger.warning(f"{self.session_name} | Failed to submit puzzle answer.")
        else:
            logger.info(f"{self.session_name} | Both Puzzle Game answer expired, please raise an issue on GitHub!")

        return None

    @error_handler
    async def check_proxy(self, http_client: aiohttp.ClientSession) -> None:
        response = await self.make_request(http_client, 'GET', url='https://httpbin.org/ip', timeout=aiohttp.ClientTimeout(5))
        if response:
            ip = response.get('origin')
            logger.info(f"{self.session_name} | Proxy IP: {ip}")
    
    #@error_handler
    async def run(self) -> None:
        if settings.USE_RANDOM_DELAY_IN_RUN:
                random_delay = random.randint(settings.RANDOM_DELAY_IN_RUN[0], settings.RANDOM_DELAY_IN_RUN[1])
                logger.info(f"{self.session_name} | Bot will start in <y>{random_delay}s</y>")
                await asyncio.sleep(random_delay)
                
        proxy_conn = ProxyConnector().from_url(self.proxy) if self.proxy else None
        http_client = aiohttp.ClientSession(headers=headers, connector=proxy_conn)
        ref_id, init_data = await self.get_tg_web_data()
        
        if not init_data:
            if not http_client.closed:
                await http_client.close()
            if proxy_conn:
                if not proxy_conn.closed:
                    proxy_conn.close()
            return
                    
        if self.proxy:
            await self.check_proxy(http_client=http_client)
        
        fake_user_agent = generate_random_user_agent(device_type='android', browser_type='chrome')
        
        
        if settings.FAKE_USERAGENT:            
            http_client.headers['User-Agent'] = fake_user_agent
        
        while True:
            try:
                if http_client.closed:
                    if proxy_conn:
                        if not proxy_conn.closed:
                            proxy_conn.close()

                    proxy_conn = ProxyConnector().from_url(self.proxy) if self.proxy else None
                    http_client = aiohttp.ClientSession(headers=headers, connector=proxy_conn)
                    if settings.FAKE_USERAGENT:            
                        http_client.headers['User-Agent'] = fake_user_agent
                
                user_data = await self.login(http_client=http_client, init_data=init_data, ref_id=ref_id)
                if not user_data:
                    logger.info(f"{self.session_name} | <r>Failed login</r>")
                    sleep_time = random.randint(settings.SLEEP_TIME[0], settings.SLEEP_TIME[1])
                    logger.info(f"{self.session_name} | Sleep <y>{sleep_time}s</y>")
                    await asyncio.sleep(delay=sleep_time)
                    continue
                http_client.headers['Authorization'] = "Bearer " + user_data.get("access_token")
                logger.info(f"{self.session_name} | <y>⭐ Login successful</y>")
                user = user_data.get('user')
                squad_id = user.get('squad_id')
                rating = await self.get_detail(http_client=http_client)
                logger.info(f"{self.session_name} | ID: <y>{user.get('id')}</y> | Points : <y>{rating}</y>")
                
                
                if settings.SQUAD_ID and squad_id is None:
                    await self.join_squad(http_client=http_client, squad_id=settings.SQUAD_ID)
                    squad_id = settings.SQUAD_ID
                    await asyncio.sleep(random.randint(1, 3))
                
                if settings.SQUAD_ID and squad_id != settings.SQUAD_ID:
                    await self.leave_squad(http_client=http_client)
                    await asyncio.sleep(random.randint(5, 7))
                    await self.join_squad(http_client=http_client, squad_id=settings.SQUAD_ID)
                    squad_id = settings.SQUAD_ID
                    await asyncio.sleep(random.randint(1, 3))
                    
                    
                logger.info(f"{self.session_name} | Squad ID: <y>{squad_id}</y>")
                data_squad = await self.get_squad(http_client=http_client, squad_id=squad_id)
                if data_squad:
                    logger.info(f"{self.session_name} | Squad : <y>{data_squad.get('name')}</y> | Member : <y>{data_squad.get('members_count')}</y> | Ratings : <y>{data_squad.get('rating')}</y>")    
                
                data_visit = await self.visit(http_client=http_client)
                if data_visit:
                    await asyncio.sleep(1)
                    logger.info(f"{self.session_name} | Daily Streak : <y>{data_visit.get('streak')}</y>")
                
                await asyncio.sleep(random.randint(1, 3))
                await self.streak(http_client=http_client)
                
                
                tasks = [
                    ('HoldCoins', self.claim_hold_coins),
                    ('SwipeCoins', self.claim_swipe_coins),
                    ('Roulette', self.claim_roulette),
                    ('Puzzle', self.puvel_puzzle),
                    ('d_tasks', self.get_daily),
                    ('m_tasks', self.get_tasks)
                ]
                
                random.shuffle(tasks)
                
                for task_name, task_func in tasks:
                    await asyncio.sleep(random.randint(5, 10))
              
                    if task_name in ['HoldCoins', 'SwipeCoins', 'Roulette', 'Puzzle']:
                        logger.info(f"{self.session_name} | Starting Game: <y>{task_name}</y>")
                        try:
                            result = await task_func(http_client=http_client)
                            if result:
                                await asyncio.sleep(random.randint(1, 3))
                                reward = "+5000⭐" if task_name == 'Puzzle' else f"+{result}⭐"
                                logger.info(f"{self.session_name} | Reward {task_name}: <y>{reward}</y>")
                            else:
                                logger.info(f"{self.session_name} | Game <y>{task_name}</y> seems to have completed.")
                        except Exception as e:
                            logger.error(f"{self.session_name} | Major Task <y>{task_name}</y> failed with error: {e}")

                    
                    elif task_name == 'd_tasks':
                        try:
                            logger.info(f"{self.session_name} | Executing Daily Tasks")
                            data_daily = await task_func(http_client=http_client)
                            if data_daily:
                                random.shuffle(data_daily)
                                for daily in data_daily:
                                    await asyncio.sleep(random.randint(5, 10))
                                    id = daily.get('id')
                                    title = daily.get('title')
                                    type = daily.get('type')
                                    if type in ('boost_channel','boost','referral','ton_transaction') or daily.get('is_completed', False):
                                        continue
                                    
                                    elif (daily.get('type') == 'subscribe_channel' or re.findall(r'(Join|Subscribe|Follow).*?channel', title, re.IGNORECASE)) and not daily.get('is_completed', False):
                                        if not settings.TASKS_WITH_JOIN_CHANNEL:
                                            continue
                                        await self.join_and_mute_tg_channel(link=daily.get('payload').get('url'))
                                        await asyncio.sleep(random.randint(5, 10))
                                    if daily:
                                        logger.info(f"{self.session_name} | Executing Daily Task: {title}")
                                        data_done = await self.done_tasks(http_client=http_client, task_id=id)
                                        if data_done and data_done.get('is_completed') is True:
                                            logger.info(f"{self.session_name} | Daily Task : <y>{title}</y> | Reward : <y>{daily.get('award')}⭐</y>")
                                        else:
                                            logger.warning(f"{self.session_name} | Daily Task {title} not completed")
                                    else:
                                        logger.warning(f"{self.session_name} | No Daily Tasks available!")
        
                                   
                            else:
                                logger.warning(f"{self.session_name} | No Daily Tasks returned")
                        except Exception as e:
                            logger.error(f"{self.session_name} | Daily Tasks failed with error: {e}")

                    
                    elif task_name == 'm_tasks':
                        try:
                            logger.info(f"{self.session_name} | Executing Main Tasks")
                            data_task = await task_func(http_client=http_client)
                            if data_task:
                                random.shuffle(data_task)
                                for task in data_task:
                                    await asyncio.sleep(random.randint(5, 10))
                                    id = task.get('id')
                                    title = task.get("title", "")
                                    type = task.get('type')
                                    if type in ('boost_channel','boost','referral','ton_transaction','ton_connect','external_api'):
                                        continue
                                    elif type == "code":
                                        await self.youtube_answers(http_client=http_client, task_id=id, task_title=title)
                                        continue
                                    
                                    elif (type == 'subscribe_channel' or re.findall(r'(Join|Subscribe|Follow).*?channel', title, re.IGNORECASE)) and not task.get('is_completed', False):
                                        if not settings.TASKS_WITH_JOIN_CHANNEL:
                                            continue
                                        await self.join_and_mute_tg_channel(link=task.get('payload').get('url'))
                                        await asyncio.sleep(random.randint(5, 10))
                                    if task:
                                        logger.info(f"{self.session_name} | Executing Main Task: {title}")
                                        data_done = await self.done_tasks(http_client=http_client, task_id=id)
                                        if data_done and data_done.get('is_completed') is True:
                                            logger.info(f"{self.session_name} | Task : <y>{title}</y> | Reward : <y>{task.get('award')}⭐</y>")
                                        else:
                                            logger.warning(f"{self.session_name} | Main Task {title} not completed")
                                    else:
                                        logger.warning(f"{self.session_name} | No Main Tasks available!")
                            else:
                                logger.warning(f"{self.session_name} | No Main Tasks returned")
                        except Exception as e:
                            logger.error(f"{self.session_name} | Main Tasks failed with error: {e}")
                    
                await http_client.close()
                if proxy_conn:
                    if not proxy_conn.closed:
                        proxy_conn.close()

            except Exception as error:
                logger.error(f"{self.session_name} | Unknown error: {error}")
                await asyncio.sleep(delay=3)
                
                   
            sleep_time = random.randint(settings.SLEEP_TIME[0], settings.SLEEP_TIME[1])
            logger.info(f"{self.session_name} | Sleep <y>{sleep_time}s</y>")
            await asyncio.sleep(delay=sleep_time)    
            
        
            

async def run_tapper(tg_client: Client, proxy: str | None):
    try:
        await Tapper(tg_client=tg_client, proxy=proxy).run()
    except InvalidSession:
        logger.error(f"{tg_client.name} | Invalid Session")
